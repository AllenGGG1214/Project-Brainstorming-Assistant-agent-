import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from psycopg import Error as PostgresError

from ..db import artifacts, dump, graph_jobs, now, runs, uid
from ..provider import public_error
from ..schemas import STAGES

log = logging.getLogger(__name__)
GRAPH_VERSION = 'basic-1'
UNCERTAIN = ('Generation was interrupted during a model call. It may have consumed API credits. '
             'Existing artifacts are preserved. Generate a new revision to retry manually.')


class State(TypedDict, total=False):
    run_id: str
    stage: str
    artifact_id: str
    outcome: str


class LeaseLost(Exception):
    pass


class UncertainCall(Exception):
    pass


class GraphRunner:
    """DB-leased runner. No secrets or full provider payloads enter checkpoints.

    A graph thread is a stage generation, with five named entry nodes. Approval
    routes to a terminal outcome; the next stage requires an explicit request.
    Recovery polling runs inside the API process for the low-traffic basic beta.
    """

    def __init__(self, db, provider, interval=5, lease_seconds=60):
        self.db, self.provider = db, provider
        self.interval, self.lease_seconds = interval, lease_seconds
        self.stop = threading.Event()
        self.thread = None

    @contextmanager
    def saver(self):
        if self.db.engine.dialect.name == 'postgresql':
            url = self.db.engine.url.set(drivername='postgresql').render_as_string(hide_password=False)
            with PostgresSaver.from_conn_string(url) as saver:
                yield saver
        else:
            with SqliteSaver.from_conn_string(self.db.path) as saver:
                yield saver

    def setup(self):
        with self.saver() as saver:
            if self.db.engine.dialect.name == 'postgresql':
                # setup includes concurrent index creation and uses autocommit.
                # A session advisory lock serializes schema setup across API starts.
                saver.conn.execute('SELECT pg_advisory_lock(306092012)')
                try:
                    saver.setup()
                finally:
                    saver.conn.execute('SELECT pg_advisory_unlock(306092012)')
            else:
                saver.setup()

    def start(self):
        self.thread = threading.Thread(target=self._poll, name='langgraph-recovery', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)

    def _poll(self):
        while not self.stop.wait(self.interval):
            try:
                self.recover_once()
            except Exception:
                # Provider/DB exceptions can include secrets. Do not log raw errors.
                log.warning('Workflow recovery temporarily unavailable.')

    def recover_once(self):
        with self.db.engine.connect() as c:
            ids = c.execute(select(graph_jobs.c.run_id).where(or_(
                graph_jobs.c.status == 'queued',
                and_(graph_jobs.c.status == 'executing', graph_jobs.c.lease_until < now())
            )).limit(20)).scalars().all()
        for run_id in ids:
            if self.stop.is_set():
                break
            self.execute(run_id)

    def _expires(self):
        return (datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)).isoformat()

    def _claim(self, run_id):
        token = uid()
        with self.db.engine.begin() as c:
            changed = c.execute(update(graph_jobs).where(and_(graph_jobs.c.run_id == run_id,
                or_(graph_jobs.c.status == 'queued', and_(graph_jobs.c.status == 'executing',
                    graph_jobs.c.lease_until < now())))).values(
                        status='executing', lease_token=token, lease_until=self._expires(), updated_at=now()))
            return token if changed.rowcount == 1 else None

    def _job(self, run_id, token=None):
        with self.db.engine.connect() as c:
            row = c.execute(select(graph_jobs).where(graph_jobs.c.run_id == run_id)).mappings().first()
        if not row or (token and (row['lease_token'] != token or row['lease_until'] < now()
                                 or row['status'] != 'executing')):
            raise LeaseLost()
        return dict(row)

    def _write(self, run_id, token, **values):
        with self.db.engine.begin() as c:
            changed = c.execute(update(graph_jobs).where(and_(graph_jobs.c.run_id == run_id,
                graph_jobs.c.lease_token == token, graph_jobs.c.status == 'executing',
                graph_jobs.c.lease_until >= now())).values(**values, updated_at=now()))
            if changed.rowcount != 1:
                raise LeaseLost()

    def _heartbeat(self, run_id, token, done):
        while not done.wait(max(0.1, self.lease_seconds / 4)):
            try:
                self._write(run_id, token, lease_until=self._expires())
            except Exception:
                return

    def build(self, saver, token):
        graph = StateGraph(State)

        def generation(state):
            job = self._job(state['run_id'], token)
            if job['result']:
                return {}  # Result ledger survives a crash before checkpointing.
            snapshot = json.loads(job['snapshot'])
            if job['call_started']:
                raise UncertainCall()
            if snapshot['project']['mode'] == 'live' and self.provider.model != snapshot['model']:
                raise ValueError('The configured model changed. Generate a new revision with the current model.')
            self._write(state['run_id'], token, call_started=1)
            content, metadata = self.provider.generate(snapshot['stage'], snapshot['project'],
                snapshot['context'], snapshot['feedback'], snapshot['previous'])
            metadata['input_snapshot'] = {'idea': snapshot['project']['idea'],
                'constraints': snapshot['project']['constraints'], 'feedback': snapshot['feedback']}
            metadata['engine'] = 'langgraph'
            metadata['graph_version'] = GRAPH_VERSION
            self._write(state['run_id'], token, result=dump({'content': content, 'metadata': metadata}))
            return {}

        def commit(state):
            job = self._job(state['run_id'], token)
            snapshot, result = json.loads(job['snapshot']), json.loads(job['result'])
            artifact_id = self.db.complete_run(state['run_id'], snapshot['project'], state['stage'],
                STAGES, result['content'], result['metadata'], lease_token=token)
            return {'artifact_id': artifact_id}

        def approval(state):
            payload = interrupt({'stage': state['stage'], 'artifact_id': state['artifact_id'],
                                 'action': 'review_and_accept'})
            job = self._job(state['run_id'], token)
            # Only transactionally recorded business approvals can resume execution.
            if not job['approval'] or payload != json.loads(job['approval']):
                raise ValueError('The workflow does not have a valid approval command.')
            if payload.get('artifact_id') != state['artifact_id']:
                raise ValueError('The approval references a different artifact.')
            with self.db.engine.connect() as c:
                artifact = c.execute(select(artifacts).where(artifacts.c.id == state['artifact_id'])).mappings().first()
            if not artifact or not artifact['approved_at'] or (
                not artifact['valid'] and payload.get('decision') != 'PIVOT'):
                raise ValueError('This workflow version has been superseded.')
            return {'outcome': payload.get('decision') or 'ACCEPT'}

        for stage in STAGES:
            graph.add_node(stage, generation)
            graph.add_edge(stage, 'save_artifact')
        graph.add_conditional_edges(START, lambda state: state['stage'], {s: s for s in STAGES})
        graph.add_node('save_artifact', commit)
        graph.add_node('await_approval', approval)
        graph.add_edge('save_artifact', 'await_approval')
        for outcome in ('ACCEPT', 'GO', 'PIVOT', 'STOP'):
            graph.add_node('done_' + outcome.lower(), lambda state: {})
            graph.add_edge('done_' + outcome.lower(), END)
        graph.add_conditional_edges('await_approval', lambda state: state['outcome'],
                                    {x: 'done_' + x.lower() for x in ('ACCEPT', 'GO', 'PIVOT', 'STOP')})
        return graph.compile(checkpointer=saver)

    def execute(self, run_id):
        token = self._claim(run_id)
        if not token:
            return
        done = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat, args=(run_id, token, done), daemon=True)
        heartbeat.start()
        try:
            job = self._job(run_id, token)
            if job['graph_version'] != GRAPH_VERSION:
                raise ValueError('This workflow version is unsupported. Generate a new revision.')
            with self.saver() as saver:
                graph = self.build(saver, token)
                config = {'configurable': {'thread_id': run_id}}
                checkpoint = graph.get_state(config)
                if not checkpoint.values:
                    snapshot = json.loads(job['snapshot'])
                    graph.invoke({'run_id': run_id, 'stage': snapshot['stage']}, config, durability='sync')
                elif checkpoint.next:
                    has_interrupt = any(task.interrupts for task in checkpoint.tasks)
                    if has_interrupt and job['approval']:
                        graph.invoke(Command(resume=json.loads(job['approval'])), config, durability='sync')
                    elif not has_interrupt:
                        graph.invoke(None, config, durability='sync')
                checkpoint = graph.get_state(config)
                # Approval may have arrived between artifact commit and interrupt.
                job = self._job(run_id, token)
                if checkpoint.next and job['approval']:
                    graph.invoke(Command(resume=json.loads(job['approval'])), config, durability='sync')
                    checkpoint = graph.get_state(config)
                with self.db.engine.begin() as c:
                    current = c.execute(select(graph_jobs).where(graph_jobs.c.run_id == run_id).with_for_update()).mappings().first()
                    if current['lease_token'] != token or current['status'] != 'executing' or current['lease_until'] < now():
                        raise LeaseLost()
                    status = 'accepted' if not checkpoint.next else (
                        'queued' if current['approval'] else 'waiting_approval')
                    c.execute(update(graph_jobs).where(graph_jobs.c.run_id == run_id).values(
                        status=status, lease_token=None, lease_until=None, updated_at=now()))
        except LeaseLost:
            pass
        except (SQLAlchemyError, PostgresError, OSError):
            # Leave the durable job leased. After expiry it resumes from its
            # checkpoint/ledger rather than treating a storage outage as a
            # failed generation. An unknown model call is still never replayed.
            log.warning('Workflow storage temporarily unavailable; recovery will retry.')
        except Exception as exc:
            message = UNCERTAIN if isinstance(exc, UncertainCall) else public_error(exc)
            try:
                with self.db.engine.begin() as c:
                    changed = c.execute(update(graph_jobs).where(and_(graph_jobs.c.run_id == run_id,
                        graph_jobs.c.lease_token == token, graph_jobs.c.status == 'executing',
                        graph_jobs.c.lease_until >= now())).values(status='needs_attention',
                            lease_token=None, lease_until=None, updated_at=now()))
                    if changed.rowcount:
                        c.execute(update(runs).where(and_(runs.c.id == run_id, runs.c.status == 'running')).values(
                            status='failed', error=message, finished_at=now()))
            except Exception:
                log.warning('Workflow failure could not yet be recorded.')
        finally:
            done.set()
            heartbeat.join(timeout=1)
