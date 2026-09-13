import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (Column, ForeignKey, Index, Integer, MetaData, String,
                        Table, Text, UniqueConstraint, and_, create_engine,
                        delete, func, inspect, select, text, update)
from sqlalchemy.exc import IntegrityError

metadata = MetaData()

users = Table(
    'users', metadata,
    Column('id', String(32), primary_key=True),
    Column('email', String(320), nullable=False, unique=True),
    Column('password_hash', Text, nullable=False),
    Column('created_at', String(40), nullable=False),
)

sessions = Table(
    'sessions', metadata,
    Column('id', String(32), primary_key=True),
    Column('user_id', String(32), ForeignKey('users.id'), nullable=False),
    Column('token_hash', String(64), nullable=False, unique=True),
    Column('expires_at', String(40), nullable=False),
    Column('created_at', String(40), nullable=False),
)

projects = Table(
    'projects', metadata,
    Column('id', String(32), primary_key=True),
    Column('user_id', String(32), ForeignKey('users.id'), nullable=True, index=True),
    Column('title', String(120), nullable=False),
    Column('idea', Text, nullable=False),
    Column('constraints_text', Text, nullable=False),
    Column('mode', String(10), nullable=False),
    Column('decision', String(10)),
    Column('created_at', String(40), nullable=False),
    Column('updated_at', String(40), nullable=False),
)

artifacts = Table(
    'artifacts', metadata,
    Column('id', String(32), primary_key=True),
    Column('project_id', String(32), ForeignKey('projects.id'), nullable=False, index=True),
    Column('stage', String(20), nullable=False),
    Column('version', Integer, nullable=False),
    Column('content', Text, nullable=False),
    Column('metadata', Text, nullable=False),
    Column('valid', Integer, nullable=False, default=1),
    Column('approved_at', String(40)),
    Column('decision', String(10)),
    Column('created_at', String(40), nullable=False),
    UniqueConstraint('project_id', 'stage', 'version'),
)

runs = Table(
    'runs', metadata,
    Column('id', String(32), primary_key=True),
    Column('project_id', String(32), ForeignKey('projects.id'), nullable=False, index=True),
    Column('stage', String(20), nullable=False),
    Column('status', String(20), nullable=False),
    Column('feedback', Text, nullable=False),
    Column('error', Text),
    Column('artifact_id', String(32), ForeignKey('artifacts.id')),
    Column('created_at', String(40), nullable=False),
    Column('finished_at', String(40)),
)

Index('one_running_per_project', runs.c.project_id, unique=True,
      sqlite_where=text("status='running'"),
      postgresql_where=text("status='running'"))

# One durable graph thread per generation. V2 runs do not have this record.
graph_jobs = Table(
    'graph_jobs', metadata,
    Column('run_id', String(32), ForeignKey('runs.id'), primary_key=True),
    Column('graph_version', String(20), nullable=False),
    Column('status', String(24), nullable=False),
    Column('snapshot', Text, nullable=False),
    Column('result', Text),
    Column('call_started', Integer, nullable=False, default=0),
    Column('approval', Text),
    Column('lease_token', String(32)),
    Column('lease_until', String(40)),
    Column('updated_at', String(40), nullable=False),
)


class DatabaseError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid4().hex


def dump(value):
    return json.dumps(value, ensure_ascii=False)


class Database:
    def __init__(self, location):
        value = str(location)
        if value.startswith('postgres://'):
            value = 'postgresql+psycopg://' + value.removeprefix('postgres://')
        elif value.startswith('postgresql://'):
            value = 'postgresql+psycopg://' + value.removeprefix('postgresql://')
        if '://' not in value:
            path = Path(value).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.path = str(path)
            value = 'sqlite:///' + path.as_posix()
        else:
            self.path = value
        kwargs = {'pool_pre_ping': True}
        if value.startswith('sqlite'):
            kwargs['connect_args'] = {'check_same_thread': False, 'timeout': 10}
        self.engine = create_engine(value, **kwargs)

    @contextmanager
    def connect(self):
        with self.engine.begin() as connection:
            yield connection

    def _migrate_legacy_sqlite(self):
        if self.engine.dialect.name != 'sqlite':
            return
        table_names = inspect(self.engine).get_table_names()
        if 'projects' not in table_names:
            return
        columns = {column['name'] for column in inspect(self.engine).get_columns('projects')}
        if 'user_id' not in columns:
            with self.engine.begin() as c:
                c.exec_driver_sql('ALTER TABLE projects ADD COLUMN user_id VARCHAR(32)')

    def init(self):
        self._migrate_legacy_sqlite()
        metadata.create_all(self.engine)
        timestamp = now()
        with self.engine.begin() as c:
            local = c.execute(select(users.c.id).where(users.c.id == 'local-user')).first()
            if not local:
                c.execute(users.insert().values(id='local-user', email='local@localhost', password_hash='disabled', created_at=timestamp))
            c.execute(update(projects).where(projects.c.user_id.is_(None)).values(user_id='local-user'))
            v3_ids = select(graph_jobs.c.run_id)
            c.execute(update(runs).where(and_(runs.c.status == 'running', runs.c.id.not_in(v3_ids))).values(status='failed', error='The service restarted before generation completed. Retry manually.', finished_at=timestamp))
            c.execute(delete(sessions).where(sessions.c.expires_at < timestamp))

    def user_count(self):
        with self.engine.connect() as c:
            return c.execute(select(func.count()).select_from(users).where(users.c.id != 'local-user')).scalar_one()

    def create_user(self, email, password_hash):
        user = {'id': uid(), 'email': email, 'password_hash': password_hash, 'created_at': now()}
        try:
            with self.engine.begin() as c:
                c.execute(users.insert().values(**user))
        except IntegrityError as exc:
            raise DatabaseError(409, 'An account with this email already exists.') from exc
        return {'id': user['id'], 'email': user['email']}

    def user_by_email(self, email):
        with self.engine.connect() as c:
            row = c.execute(select(users).where(users.c.email == email)).mappings().first()
            return dict(row) if row else None

    def create_session(self, user_id, token_hash, days=30):
        with self.engine.begin() as c:
            c.execute(sessions.insert().values(id=uid(), user_id=user_id, token_hash=token_hash,
                                               expires_at=(datetime.now(timezone.utc) + timedelta(days=days)).isoformat(), created_at=now()))

    def session_user(self, token_hash):
        with self.engine.connect() as c:
            row = c.execute(select(users.c.id, users.c.email).select_from(
                sessions.join(users, sessions.c.user_id == users.c.id)
            ).where(and_(sessions.c.token_hash == token_hash, sessions.c.expires_at > now()))).mappings().first()
            return dict(row) if row else None

    def delete_session(self, token_hash):
        with self.engine.begin() as c:
            c.execute(delete(sessions).where(sessions.c.token_hash == token_hash))

    def get_project(self, project_id, user_id='local-user'):
        with self.engine.connect() as c:
            row = c.execute(select(projects).where(and_(projects.c.id == project_id, projects.c.user_id == user_id))).mappings().first()
            if not row:
                raise DatabaseError(404, 'Project not found.')
            result = dict(row)
            result['constraints'] = result.pop('constraints_text')
            return result

    def list_projects(self, user_id):
        accepted = select(func.count()).select_from(artifacts).where(and_(artifacts.c.project_id == projects.c.id, artifacts.c.valid == 1, artifacts.c.approved_at.is_not(None))).scalar_subquery()
        with self.engine.connect() as c:
            rows = c.execute(select(projects, accepted.label('accepted_count')).where(projects.c.user_id == user_id).order_by(projects.c.updated_at.desc())).mappings()
            return [{**dict(row), 'constraints': row['constraints_text']} for row in rows]

    def create_project(self, user_id, title, idea, constraints, mode):
        project_id = uid()
        timestamp = now()
        with self.engine.begin() as c:
            c.execute(projects.insert().values(id=project_id, user_id=user_id, title=title, idea=idea,
                                               constraints_text=constraints, mode=mode, decision=None,
                                               created_at=timestamp, updated_at=timestamp))
        return self.detail(project_id, user_id)

    def detail(self, project_id, user_id='local-user'):
        project = self.get_project(project_id, user_id)
        with self.engine.connect() as c:
            artifact_rows = c.execute(select(artifacts).where(artifacts.c.project_id == project_id).order_by(artifacts.c.created_at.desc())).mappings()
            run_rows = c.execute(select(runs).where(runs.c.project_id == project_id).order_by(runs.c.created_at.desc()).limit(50)).mappings()
            project['artifacts'] = [{**dict(a), 'content': json.loads(a['content']), 'metadata': json.loads(a['metadata'])} for a in artifact_rows]
            project['runs'] = [dict(r) for r in run_rows]
            jobs = c.execute(select(graph_jobs.c.run_id, graph_jobs.c.status).where(
                graph_jobs.c.run_id.in_([r['id'] for r in project['runs']]))).mappings().all()
            statuses = {j['run_id']: j['status'] for j in jobs}
            for run in project['runs']:
                if run['id'] in statuses:
                    run['engine'] = 'langgraph'
                    run['workflow_status'] = statuses[run['id']]
            return project

    def prepare_run(self, project_id, user_id, stage, stage_order, feedback, daily_limit, graph=False, model=None):
        timestamp = now()
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        try:
            with self.engine.begin() as c:
                project_row = c.execute(select(projects).where(and_(projects.c.id == project_id, projects.c.user_id == user_id)).with_for_update()).mappings().first()
                if not project_row:
                    raise DatabaseError(404, 'Project not found.')
                project = dict(project_row)
                project['constraints'] = project.pop('constraints_text')
                if project['decision'] == 'STOP':
                    raise DatabaseError(409, 'This project has been stopped. Create a new project to explore another direction.')
                artifact_rows = c.execute(select(artifacts).where(and_(artifacts.c.project_id == project_id, artifacts.c.valid == 1))).mappings().all()
                active = {row['stage']: dict(row) for row in artifact_rows}
                for earlier in stage_order[:stage_order.index(stage)]:
                    if earlier not in active or not active[earlier]['approved_at']:
                        raise DatabaseError(409, 'Generate and accept every earlier stage first.')
                if stage_order.index(stage) > 1 and project['decision'] != 'GO':
                    raise DatabaseError(409, 'Choose GO in the Research stage first. A PIVOT requires a new brief and research pass.')
                count = c.execute(select(func.count()).select_from(runs.join(projects, runs.c.project_id == projects.c.id)).where(and_(projects.c.user_id == user_id, projects.c.mode == 'live', runs.c.created_at >= day_start))).scalar_one()
                if project['mode'] == 'live' and daily_limit > 0 and count >= daily_limit:
                    raise DatabaseError(429, f'Daily generation limit reached ({daily_limit}). Try again tomorrow.')
                run_id = uid()
                c.execute(runs.insert().values(id=run_id, project_id=project_id, stage=stage, status='running', feedback=feedback, created_at=timestamp))
                context = {s: json.loads(active[s]['content']) for s in stage_order[:stage_order.index(stage)]}
                previous = json.loads(active[stage]['content']) if stage in active else None
                if graph:
                    snapshot = {'run_id': run_id, 'project': project, 'stage': stage,
                                'context': context, 'feedback': feedback, 'previous': previous, 'model': model}
                    c.execute(graph_jobs.insert().values(run_id=run_id, graph_version='basic-1',
                        status='queued', snapshot=dump(snapshot), call_started=0, updated_at=timestamp))
                return run_id, project, context, previous
        except IntegrityError as exc:
            raise DatabaseError(409, 'This project is already generating. Wait for it to finish.') from exc

    def complete_run(self, run_id, project, stage, stage_order, content, metadata_blob, lease_token=None):
        with self.engine.begin() as c:
            c.execute(select(projects.c.id).where(projects.c.id == project['id']).with_for_update()).first()
            if lease_token is not None:
                job = c.execute(select(graph_jobs).where(graph_jobs.c.run_id == run_id).with_for_update()).mappings().first()
                if not job or job['lease_token'] != lease_token or job['lease_until'] < now():
                    raise DatabaseError(409, 'Execution lease expired; recovery will continue safely.')
            run = c.execute(select(runs.c.status, runs.c.artifact_id).where(runs.c.id == run_id).with_for_update()).first()
            if run and run.status == 'succeeded':
                return run.artifact_id
            if not run or run.status != 'running':
                raise DatabaseError(409, 'This run is no longer active.')
            version = c.execute(select(func.coalesce(func.max(artifacts.c.version), 0) + 1).where(and_(artifacts.c.project_id == project['id'], artifacts.c.stage == stage))).scalar_one()
            affected = stage_order[stage_order.index(stage):]
            old_runs = select(runs.c.id).where(and_(runs.c.project_id == project['id'],
                runs.c.stage.in_(affected), runs.c.id != run_id))
            c.execute(update(graph_jobs).where(and_(graph_jobs.c.run_id.in_(old_runs),
                graph_jobs.c.status.in_(['waiting_approval', 'queued', 'executing']))).values(status='superseded', updated_at=now()))
            c.execute(update(artifacts).where(and_(artifacts.c.project_id == project['id'], artifacts.c.stage.in_(affected))).values(valid=0))
            artifact_id = uid()
            c.execute(artifacts.insert().values(id=artifact_id, project_id=project['id'], stage=stage, version=version,
                                                content=dump(content), metadata=dump(metadata_blob), valid=1, created_at=now()))
            values = {'updated_at': now()}
            if stage_order.index(stage) <= 1:
                values['decision'] = None
            c.execute(update(projects).where(projects.c.id == project['id']).values(**values))
            c.execute(update(runs).where(runs.c.id == run_id).values(status='succeeded', artifact_id=artifact_id, finished_at=now()))
            return artifact_id

    def fail_run(self, run_id, message):
        with self.engine.begin() as c:
            c.execute(update(runs).where(runs.c.id == run_id).values(status='failed', error=message, finished_at=now()))

    def recover_graph_approval(self, project_id, user_id, run_id):
        with self.engine.begin() as c:
            project = c.execute(select(projects).where(and_(projects.c.id == project_id,
                projects.c.user_id == user_id)).with_for_update()).first()
            if not project:
                raise DatabaseError(404, 'Project not found.')
            run = c.execute(select(runs).where(and_(runs.c.id == run_id,
                runs.c.project_id == project_id))).mappings().first()
            job = c.execute(select(graph_jobs).where(graph_jobs.c.run_id == run_id).with_for_update()).mappings().first()
            if not run or not job:
                raise DatabaseError(404, 'Workflow not found.')
            if job['status'] != 'needs_attention' or run['status'] != 'succeeded' or not job['result']:
                raise DatabaseError(409, 'This workflow cannot be synchronized. Generate a new revision to retry manually.')
            artifact = c.execute(select(artifacts).where(artifacts.c.id == run['artifact_id'])).mappings().first()
            decision = json.loads(job['approval']).get('decision') if job['approval'] else None
            if not artifact or (not artifact['valid'] and decision != 'PIVOT'):
                raise DatabaseError(409, 'This workflow version is stale.')
            c.execute(update(graph_jobs).where(graph_jobs.c.run_id == run_id).values(
                status='queued', lease_token=None, lease_until=None, updated_at=now()))

    def accept(self, project_id, user_id, stage, stage_order, artifact_id, decision, revised_idea):
        with self.engine.begin() as c:
            project = c.execute(select(projects).where(and_(projects.c.id == project_id, projects.c.user_id == user_id)).with_for_update()).mappings().first()
            if not project:
                raise DatabaseError(404, 'Project not found.')
            if c.execute(select(runs.c.id).where(and_(runs.c.project_id == project_id, runs.c.status == 'running'))).first():
                raise DatabaseError(409, 'This project is already generating. Wait for it to finish.')
            rows = c.execute(select(artifacts).where(and_(artifacts.c.project_id == project_id, artifacts.c.valid == 1))).mappings().all()
            active = {row['stage']: dict(row) for row in rows}
            artifact = active.get(stage)
            if not artifact or artifact['id'] != artifact_id:
                raise DatabaseError(409, 'This version is stale. Refresh and accept the current version.')
            if artifact['approved_at']:
                raise DatabaseError(409, 'This version is already accepted. Generate a revision to change it.')
            if project['decision'] == 'STOP':
                raise DatabaseError(409, 'This project has been stopped.')
            for earlier in stage_order[:stage_order.index(stage)]:
                if earlier not in active or not active[earlier]['approved_at']:
                    raise DatabaseError(409, 'An earlier stage has not been accepted.')
            if stage == 'research':
                if not decision:
                    raise DatabaseError(422, 'Choose GO, PIVOT, or STOP.')
                if decision == 'PIVOT' and len(revised_idea.strip()) < 10:
                    raise DatabaseError(422, 'Describe the revised direction in at least 10 characters. The workflow will restart at the brief and research stages.')
                values = {'decision': decision, 'updated_at': now()}
                if decision == 'PIVOT':
                    values['idea'] = revised_idea.strip()
                    c.execute(update(artifacts).where(artifacts.c.project_id == project_id).values(valid=0))
                c.execute(update(projects).where(projects.c.id == project_id).values(**values))
            elif decision is not None:
                raise DatabaseError(422, 'Only the Research stage accepts a GO, PIVOT, or STOP decision.')
            c.execute(update(artifacts).where(artifacts.c.id == artifact_id).values(approved_at=now(), decision=decision))
            graph_run = c.execute(select(runs.c.id).where(runs.c.artifact_id == artifact_id)).scalar()
            if graph_run:
                payload = dump({'artifact_id': artifact_id, 'decision': decision, 'accepted': True})
                # The command and business approval share this transaction. The runner
                # consumes it after reaching interrupt; checkpoint writes are separate.
                c.execute(update(graph_jobs).where(and_(graph_jobs.c.run_id == graph_run,
                    graph_jobs.c.status.in_(['executing', 'waiting_approval', 'queued', 'needs_attention']))).values(
                        approval=payload, updated_at=now()))
                c.execute(update(graph_jobs).where(and_(graph_jobs.c.run_id == graph_run,
                    graph_jobs.c.status.in_(['waiting_approval', 'needs_attention']))).values(status='queued'))
            if decision == 'PIVOT':
                project_runs = select(runs.c.id).where(and_(runs.c.project_id == project_id, runs.c.id != graph_run))
                c.execute(update(graph_jobs).where(and_(graph_jobs.c.run_id.in_(project_runs),
                    graph_jobs.c.status.in_(['waiting_approval', 'queued']))).values(status='superseded', updated_at=now()))
            c.execute(update(projects).where(projects.c.id == project_id).values(updated_at=now()))
        return self.detail(project_id, user_id)
