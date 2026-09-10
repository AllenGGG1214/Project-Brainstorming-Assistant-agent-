import io
import json
import threading
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db import Database, now, runs, uid
from app.main import create_app
from app.provider import Provider, extract_evidence
from app.schemas import Functions, STAGES


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / 'test.db', Provider('', 'test-model'))
    with TestClient(app) as c:
        yield c


def create(client, mode='demo'):
    return client.post('/api/projects', json={'title': 'Reading assistant', 'idea': 'Help students record paper notes, filter by topic, and export sources.', 'constraints': 'Four weeks, solo developer', 'mode': mode})


def generate(client, pid, stage):
    response = client.post(f'/api/projects/{pid}/stages/{stage}/generate', json={})
    assert response.status_code == 202, response.text
    detail = client.get(f'/api/projects/{pid}').json()
    assert detail['runs'][0]['status'] == 'succeeded', detail['runs'][0]
    return next(a for a in detail['artifacts'] if a['stage'] == stage and a['valid'])


def accept(client, pid, stage, artifact, decision=None, **kwargs):
    return client.post(f'/api/projects/{pid}/stages/{stage}/accept', json={'artifact_id': artifact['id'], 'decision': decision, **kwargs})


def through(client, pid, stages):
    artifacts = {}
    for stage in stages:
        artifact = generate(client, pid, stage)
        assert accept(client, pid, stage, artifact, 'GO' if stage == 'research' else None).status_code == 200
        artifacts[stage] = artifact
    return artifacts


def test_five_stage_flow_export_and_persistence(client):
    p = create(client).json()
    result = through(client, p['id'], STAGES)
    assert len(result) == 5
    assert client.get('/api/projects').json()[0]['accepted_count'] == 5
    response = client.get(f'/api/projects/{p["id"]}/export')
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        assert {'project-state.json', 'sources.json', '03-functional-list.csv', '04-prototype/index.html', 'architecture.mmd'} <= set(z.namelist())
        snapshot = json.loads(z.read('project-state.json'))
        assert all(a['approved_at'] for a in snapshot['artifacts'])
        assert 'data-function-id="FL-001"' in z.read('04-prototype/index.html').decode()
        assert snapshot['mode'] == 'demo'
    reopened = Database(client.app.state.db.path)
    assert reopened.detail(p['id'])['decision'] == 'GO'


def test_cannot_skip_stages_or_auto_accept_recommendation(client):
    pid = create(client).json()['id']
    assert client.post(f'/api/projects/{pid}/stages/functions/generate', json={}).status_code == 409
    through(client, pid, ['organize'])
    artifact = generate(client, pid, 'research')
    assert artifact['content']['recommendation'] == 'GO'
    assert client.post(f'/api/projects/{pid}/stages/functions/generate', json={}).status_code == 409
    assert accept(client, pid, 'research', artifact).status_code == 422


def test_revision_invalidates_downstream_keeps_accepted_history(client):
    pid = create(client).json()['id']
    old = through(client, pid, STAGES)
    new = generate(client, pid, 'organize')
    assert new['version'] == 2
    detail = client.get(f'/api/projects/{pid}').json()
    assert detail['decision'] is None
    assert len(detail['artifacts']) == 6
    assert sum(a['valid'] for a in detail['artifacts']) == 1
    assert next(a for a in detail['artifacts'] if a['id'] == old['organize']['id'])['approved_at']
    assert accept(client, pid, 'organize', old['organize']).status_code == 409
    assert client.post(f'/api/projects/{pid}/stages/functions/generate', json={}).status_code == 409


@pytest.mark.parametrize('decision', ['PIVOT', 'STOP'])
def test_decision_paths(client, decision):
    pid = create(client).json()['id']
    through(client, pid, ['organize'])
    artifact = generate(client, pid, 'research')
    if decision == 'PIVOT':
        assert accept(client, pid, 'research', artifact, decision).status_code == 422
    revised = 'Help graduate students organize replication results and reading notes by topic.'
    r = accept(client, pid, 'research', artifact, decision, revised_idea=revised)
    assert r.status_code == 200
    assert client.post(f'/api/projects/{pid}/stages/functions/generate', json={}).status_code == 409
    if decision == 'PIVOT':
        assert r.json()['idea'] == revised
        assert not any(a['valid'] for a in r.json()['artifacts'])
        through(client, pid, ['organize', 'research', 'functions'])
    else:
        assert client.post(f'/api/projects/{pid}/stages/organize/generate', json={}).status_code == 409
        assert client.get(f'/api/projects/{pid}/export').status_code == 200


def test_live_requires_key_and_no_secret_in_health(client):
    assert create(client, 'live').status_code == 400
    assert client.get('/api/health').json() == {'status': 'ok', 'live_available': False, 'model': 'test-model', 'auth_required': False}
    assert client.get('/api/projects/missing').status_code == 404
    assert client.post('/api/projects', json={'title': '   ', 'idea': ' ' * 20}).status_code == 422


def test_failure_does_not_destroy_previous_artifact(tmp_path):
    class FailingProvider(Provider):
        fail = False
        def generate(self, *args):
            if self.fail:
                raise RuntimeError('secret should not be exposed')
            return super().generate(*args)
    provider = FailingProvider('', 'test')
    with TestClient(create_app(tmp_path / 'fail.db', provider)) as client:
        pid = create(client).json()['id']
        original = through(client, pid, ['organize'])['organize']
        provider.fail = True
        assert client.post(f'/api/projects/{pid}/stages/organize/generate', json={}).status_code == 202
        detail = client.get(f'/api/projects/{pid}').json()
        assert detail['runs'][0]['status'] == 'failed'
        assert 'secret' not in detail['runs'][0]['error']
        assert detail['artifacts'][0]['id'] == original['id']
        assert detail['artifacts'][0]['valid'] == 1
        provider.fail = False
        assert generate(client, pid, 'organize')['version'] == 2


def test_concurrent_request_is_rejected(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class SlowProvider(Provider):
        def generate(self, *args):
            entered.set()
            assert release.wait(10)
            return super().generate(*args)
    with TestClient(create_app(tmp_path / 'concurrent.db', SlowProvider('', 'test'))) as client:
        pid = create(client).json()['id']
        response = []
        thread = threading.Thread(target=lambda: response.append(client.post(f'/api/projects/{pid}/stages/organize/generate', json={})))
        thread.start()
        try:
            assert entered.wait(5)
            assert client.post(f'/api/projects/{pid}/stages/organize/generate', json={}).status_code == 409
        finally:
            release.set()
            thread.join(10)
        assert response[0].status_code == 202


def test_restart_marks_inflight_job_failed(tmp_path):
    path = tmp_path / 'restart.db'
    with TestClient(create_app(path, Provider('', 'test'))) as client:
        pid = create(client).json()['id']
        with client.app.state.db.connect() as c:
            c.execute(runs.insert().values(id=uid(), project_id=pid, stage='organize', status='running', feedback='', created_at=now()))
    with TestClient(create_app(path, Provider('', 'test'))) as client:
        detail = client.get(f'/api/projects/{pid}').json()
        assert detail['runs'][0]['status'] == 'failed'
        assert 'restarted' in detail['runs'][0]['error']
        generate(client, pid, 'organize')


def test_evidence_comes_from_tools_and_annotations():
    payload = {'output': [{'type': 'web_search_call', 'action': {'type': 'search', 'queries': ['paper notes'], 'sources': [{'url': 'https://example.com', 'title': 'Example'}, {'url': 'javascript:alert(1)'}]}}, {'type': 'message', 'content': [{'annotations': [{'type': 'url_citation', 'url': 'https://example.org', 'title': 'Org', 'start_index': 0, 'end_index': 5}]}]}]}
    result = extract_evidence(SimpleNamespace(model_dump=lambda: payload, output_text='A report with https://fabricated.test'))
    assert {s['url'] for s in result['sources']} == {'https://example.com', 'https://example.org'}
    assert result['queries'] == ['paper notes']
    assert len(result['citations']) == 1


def test_estimate_and_dependency_validation(client):
    pid = create(client).json()['id']
    through(client, pid, ['organize', 'research'])
    data = generate(client, pid, 'functions')['content']
    data['functions'][0]['low_days'] = 100
    with pytest.raises(ValidationError):
        Functions.model_validate(data)
    data['functions'][0]['low_days'] = 1
    data['functions'][0]['dependencies'] = ['FL-003']
    with pytest.raises(ValidationError):
        Functions.model_validate(data)
