"""Durability tests run on SQLite, and PostgreSQL when TEST_DATABASE_URL is set.

The PostgreSQL URL must point to an isolated test database; tables are reset.
"""
import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from app.db import Database, artifacts, graph_jobs, runs
from app.main import create_app
from app.orchestration.runner import GraphRunner, LeaseLost
from app.provider import Provider
from app.schemas import STAGES
from test_workflow import accept, create, generate, through


class CountingProvider(Provider):
    def __init__(self):
        super().__init__('', 'test-model')
        self.calls = 0

    def generate(self, *args):
        self.calls += 1
        return super().generate(*args)


@pytest.fixture(params=['sqlite', 'postgres'])
def location(request, tmp_path):
    if request.param == 'sqlite':
        return tmp_path / 'graph.db'
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to an isolated PostgreSQL test database.')
    db = Database(url)
    db.init()
    with db.connect() as c:
        c.execute(delete(graph_jobs))
        c.execute(delete(runs))
        c.execute(delete(artifacts))
    db.engine.dispose()
    return url


def pending(db, pid, provider):
    run_id, *_ = db.prepare_run(pid, 'local-user', 'organize', STAGES, '', 0,
                               graph=True, model=provider.model)
    return run_id


def get_job(db, run_id):
    with db.engine.connect() as c:
        return dict(c.execute(select(graph_jobs).where(graph_jobs.c.run_id == run_id)).mappings().one())


def expire(db, run_id):
    with db.connect() as c:
        c.execute(update(graph_jobs).where(graph_jobs.c.run_id == run_id).values(
            status='executing', lease_until='2000-01-01T00:00:00+00:00', lease_token='old-worker'))


def checkpoint(runner, run_id):
    with runner.saver() as saver:
        return runner.build(saver, None).get_state({'configurable': {'thread_id': run_id}})


def test_every_stage_interrupts_and_approval_routes(location):
    provider = CountingProvider()
    with TestClient(create_app(location, provider)) as client:
        pid = create(client).json()['id']
        for stage in STAGES:
            artifact = generate(client, pid, stage)
            run_id = client.app.state.db.detail(pid)['runs'][0]['id']
            runner = client.app.state.runner
            state = checkpoint(runner, run_id)
            assert state.next == ('await_approval',)
            assert any(task.interrupts for task in state.tasks)
            assert get_job(runner.db, run_id)['status'] == 'waiting_approval'
            assert accept(client, pid, stage, artifact, 'GO' if stage == 'research' else None).status_code == 200
            state = checkpoint(runner, run_id)
            assert not state.next
            assert state.values['outcome'] == ('GO' if stage == 'research' else 'ACCEPT')
        assert provider.calls == 5


def test_queued_run_and_saved_approval_survive_restart(location):
    provider = CountingProvider()
    with TestClient(create_app(location, provider)) as client:
        pid = create(client).json()['id']
        run_id = pending(client.app.state.db, pid, provider)
    with TestClient(create_app(location, provider)) as client:
        runner = client.app.state.runner
        assert runner.db.detail(pid)['runs'][0]['status'] == 'running'
        runner.recover_once()
        artifact = runner.db.detail(pid)['artifacts'][0]
        # Commit approval without executing the background task, then restart.
        runner.db.accept(pid, 'local-user', 'organize', STAGES, artifact['id'], None, '')
    with TestClient(create_app(location, provider)) as client:
        client.app.state.runner.recover_once()
        assert get_job(client.app.state.db, run_id)['status'] == 'accepted'
        assert provider.calls == 1


def test_result_saved_before_checkpoint_reuses_ledger(location):
    provider = CountingProvider()
    with TestClient(create_app(location, provider)) as client:
        runner = client.app.state.runner
        pid = create(client).json()['id']
        run_id = pending(runner.db, pid, provider)
        job = get_job(runner.db, run_id)
        snapshot = json.loads(job['snapshot'])
        content, metadata = provider.generate('organize', snapshot['project'], {}, '', None)
        with runner.db.connect() as c:
            c.execute(update(graph_jobs).where(graph_jobs.c.run_id == run_id).values(
                call_started=1, result=json.dumps({'content': content, 'metadata': metadata})))
        expire(runner.db, run_id)
        runner.recover_once()
        runner.execute(run_id)
        assert provider.calls == 1
        assert len(runner.db.detail(pid)['artifacts']) == 1
        assert get_job(runner.db, run_id)['status'] == 'waiting_approval'


def test_crash_after_artifact_commit_is_idempotent(location):
    class Crash(BaseException):
        pass

    provider = CountingProvider()
    with TestClient(create_app(location, provider)) as client:
        runner = client.app.state.runner
        pid = create(client).json()['id']
        run_id = pending(runner.db, pid, provider)
        original = runner.db.complete_run

        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise Crash()

        runner.db.complete_run = crash
        with pytest.raises(Crash):
            runner.execute(run_id)
        runner.db.complete_run = original
        expire(runner.db, run_id)
        runner.recover_once()
        assert len(runner.db.detail(pid)['artifacts']) == 1
        assert provider.calls == 1
        assert checkpoint(runner, run_id).next == ('await_approval',)


def test_unknown_model_call_requires_manual_retry(location):
    provider = CountingProvider()
    with TestClient(create_app(location, provider)) as client:
        runner = client.app.state.runner
        pid = create(client).json()['id']
        run_id = pending(runner.db, pid, provider)
        with runner.db.connect() as c:
            c.execute(update(graph_jobs).where(graph_jobs.c.run_id == run_id).values(call_started=1))
        expire(runner.db, run_id)
        runner.recover_once()
        assert provider.calls == 0
        detail = runner.db.detail(pid)
        assert detail['runs'][0]['status'] == 'failed'
        assert 'credits' in detail['runs'][0]['error']
        runner.recover_once()
        assert provider.calls == 0
        assert generate(client, pid, 'organize')['version'] == 1


def test_lease_fences_previous_worker_and_claim_is_exclusive(location):
    provider = CountingProvider()
    with TestClient(create_app(location, provider)) as client:
        runner = client.app.state.runner
        pid = create(client).json()['id']
        run_id = pending(runner.db, pid, provider)
        first = runner._claim(run_id)
        assert first
        assert runner._claim(run_id) is None
        expire(runner.db, run_id)
        second = runner._claim(run_id)
        assert second and first != second
        with pytest.raises(LeaseLost):
            runner._write(run_id, first, result='{}')
        snapshot = json.loads(get_job(runner.db, run_id)['snapshot'])
        with pytest.raises(Exception, match='lease expired'):
            runner.db.complete_run(run_id, snapshot['project'], 'organize', STAGES, {}, {}, lease_token=first)


def test_upstream_revision_supersedes_old_interrupt(location):
    with TestClient(create_app(location, CountingProvider())) as client:
        pid = create(client).json()['id']
        through(client, pid, ['organize'])
        old = generate(client, pid, 'research')
        old_id = client.app.state.db.detail(pid)['runs'][0]['id']
        generate(client, pid, 'organize')
        assert get_job(client.app.state.db, old_id)['status'] == 'superseded'
        assert accept(client, pid, 'research', old, 'GO').status_code == 409


@pytest.mark.parametrize('decision', ['PIVOT', 'STOP'])
def test_research_terminal_branches(location, decision):
    with TestClient(create_app(location, CountingProvider())) as client:
        pid = create(client).json()['id']
        through(client, pid, ['organize'])
        artifact = generate(client, pid, 'research')
        run_id = client.app.state.db.detail(pid)['runs'][0]['id']
        response = accept(client, pid, 'research', artifact, decision,
                          revised_idea='An alternative reading assistant for replication studies.')
        assert response.status_code == 200
        assert checkpoint(client.app.state.runner, run_id).values['outcome'] == decision
        assert not checkpoint(client.app.state.runner, run_id).next


def test_legacy_project_can_continue_on_v3(location):
    provider = CountingProvider()
    with TestClient(create_app(location, provider, {'workflow_engine': 'v2'})) as client:
        pid = create(client).json()['id']
        artifact = generate(client, pid, 'organize')
    with TestClient(create_app(location, provider)) as client:
        assert accept(client, pid, 'organize', artifact).status_code == 200
        research = generate(client, pid, 'research')
        assert research['metadata']['engine'] == 'langgraph'
        assert accept(client, pid, 'research', research, 'GO').status_code == 200
        assert client.get(f'/api/projects/{pid}/export').status_code == 200


def test_failed_synchronization_can_be_recovered_without_regeneration(location):
    provider = CountingProvider()
    with TestClient(create_app(location, provider)) as client:
        runner = client.app.state.runner
        pid = create(client).json()['id']
        artifact = generate(client, pid, 'organize')
        run_id = runner.db.detail(pid)['runs'][0]['id']
        with runner.db.connect() as c:
            c.execute(update(graph_jobs).where(graph_jobs.c.run_id == run_id).values(status='needs_attention'))
        response = client.post(f'/api/projects/{pid}/runs/{run_id}/recover', json={})
        assert response.status_code == 202
        assert provider.calls == 1
        assert get_job(runner.db, run_id)['status'] == 'waiting_approval'
        assert client.post(f'/api/projects/missing/runs/{run_id}/recover', json={}).status_code == 404
        assert accept(client, pid, 'organize', artifact).status_code == 200
        assert get_job(runner.db, run_id)['status'] == 'accepted'


def test_accept_can_resume_after_workflow_sync_failure(location):
    with TestClient(create_app(location, CountingProvider())) as client:
        runner = client.app.state.runner
        pid = create(client).json()['id']
        artifact = generate(client, pid, 'organize')
        run_id = runner.db.detail(pid)['runs'][0]['id']
        with runner.db.connect() as c:
            c.execute(update(graph_jobs).where(graph_jobs.c.run_id == run_id).values(status='needs_attention'))
        assert accept(client, pid, 'organize', artifact).status_code == 200
        assert get_job(runner.db, run_id)['status'] == 'accepted'
