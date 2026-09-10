import csv
import hmac
import io
import os
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response

from .auth import COOKIE_NAME, hash_password, new_token, token_hash, verify_password
from .db import Database, DatabaseError, dump
from .provider import Provider, public_error
from .schemas import AcceptRequest, GenerateRequest, LoginRequest, ProjectCreate, RegisterRequest, STAGES, Stage

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')
FILENAMES = dict(zip(STAGES, ['01-idea-brief.md', '02-research-and-brainstorm.md', '03-functional-list.md', '04-prototype/prototype-map.md', '05-architecture.md']))


def env_bool(name, default=False):
    value = os.getenv(name)
    return default if value is None else value.lower() in {'1', 'true', 'yes', 'on'}


def env_list(name, default):
    value = os.getenv(name, '')
    return [part.strip() for part in value.split(',') if part.strip()] or default


def create_app(db_path=None, provider=None, settings=None):
    config = {
        'auth_required': env_bool('AUTH_REQUIRED'), 'allow_signups': env_bool('ALLOW_SIGNUPS', True),
        'invite_code': os.getenv('INVITE_CODE', ''), 'cookie_secure': env_bool('COOKIE_SECURE'),
        'session_days': int(os.getenv('SESSION_DAYS', '30')),
        'daily_limit': int(os.getenv('DAILY_GENERATION_LIMIT', '0')),
        'cors_origins': env_list('CORS_ORIGINS', ['http://localhost:3000', 'http://127.0.0.1:3000']),
        'trusted_hosts': env_list('TRUSTED_HOSTS', ['localhost', '127.0.0.1', 'testserver']),
    }
    config.update(settings or {})
    location = db_path or os.getenv('DATABASE_URL') or ROOT / os.getenv('DATABASE_PATH', 'data/brainstorm.db')
    db = Database(location)
    generator = provider or Provider(os.getenv('OPENAI_API_KEY', ''), os.getenv('OPENAI_MODEL', 'gpt-5.5'))

    @asynccontextmanager
    async def lifespan(app):
        if config['auth_required'] and config['allow_signups'] and not config['invite_code']:
            raise RuntimeError('INVITE_CODE is required when production signups are enabled.')
        db.init()
        yield

    app = FastAPI(title='Idea Atelier API', version='2.1.0', lifespan=lifespan)
    app.state.db, app.state.config = db, config
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config['trusted_hosts'])
    app.add_middleware(CORSMiddleware, allow_origins=config['cors_origins'], allow_credentials=True,
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])

    def fail(exc):
        raise HTTPException(exc.status, exc.message)

    def current_user(request: Request):
        if not config['auth_required']:
            return {'id': 'local-user', 'email': 'local@localhost'}
        token = request.cookies.get(COOKIE_NAME)
        user = db.session_user(token_hash(token)) if token else None
        if not user:
            raise HTTPException(401, 'Sign in to continue.')
        return user

    def public_user(request: Request):
        if not config['auth_required']:
            return {'id': 'local-user', 'email': 'local@localhost'}
        token = request.cookies.get(COOKIE_NAME)
        return db.session_user(token_hash(token)) if token else None

    def issue_session(response, user):
        token = new_token()
        db.create_session(user['id'], token_hash(token), config['session_days'])
        response.set_cookie(COOKIE_NAME, token, max_age=config['session_days'] * 86400, httponly=True,
                            secure=config['cookie_secure'], samesite='lax', path='/')

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'live_available': bool(generator.api_key), 'model': generator.model,
                'auth_required': config['auth_required']}

    @app.get('/api/auth/status')
    def auth_status(user=Depends(public_user)):
        return {'required': config['auth_required'], 'authenticated': bool(user),
                'registration_enabled': bool(config['allow_signups'] and config['invite_code']),
                'user': {'email': user['email']} if user else None}

    @app.post('/api/auth/register', status_code=201)
    def register(body: RegisterRequest, response: Response):
        if not config['auth_required'] or not config['allow_signups']:
            raise HTTPException(404, 'Registration is unavailable.')
        if not hmac.compare_digest(body.invite_code, config['invite_code']):
            raise HTTPException(403, 'The invite code is invalid.')
        email = body.email.strip().lower()
        if '@' not in email or email.startswith('@') or email.endswith('@'):
            raise HTTPException(422, 'Enter a valid email address.')
        try:
            user = db.create_user(email, hash_password(body.password))
        except DatabaseError as exc:
            fail(exc)
        issue_session(response, user)
        return {'email': user['email']}

    @app.post('/api/auth/login')
    def login(body: LoginRequest, response: Response):
        user = db.user_by_email(body.email.strip().lower())
        if not user or not verify_password(body.password, user['password_hash']):
            raise HTTPException(401, 'Email or password is incorrect.')
        issue_session(response, user)
        return {'email': user['email']}

    @app.post('/api/auth/logout', status_code=204)
    def logout(request: Request):
        token = request.cookies.get(COOKIE_NAME)
        if token:
            db.delete_session(token_hash(token))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, path='/', secure=config['cookie_secure'], httponly=True, samesite='lax')
        return response

    @app.get('/api/projects')
    def list_projects(user=Depends(current_user)):
        return db.list_projects(user['id'])

    @app.post('/api/projects', status_code=201)
    def create_project(body: ProjectCreate, user=Depends(current_user)):
        if body.mode == 'live' and not generator.api_key:
            raise HTTPException(400, 'Live generation is not configured on this deployment.')
        return db.create_project(user['id'], body.title, body.idea, body.constraints, body.mode)

    @app.get('/api/projects/{project_id}')
    def get_project(project_id: str, user=Depends(current_user)):
        try:
            return db.detail(project_id, user['id'])
        except DatabaseError as exc:
            fail(exc)

    def generate_job(run_id, project, stage, context, feedback, previous):
        try:
            content, metadata_blob = generator.generate(stage, project, context, feedback, previous)
            metadata_blob['input_snapshot'] = {'idea': project['idea'], 'constraints': project['constraints'], 'feedback': feedback}
            db.complete_run(run_id, project, stage, STAGES, content, metadata_blob)
        except Exception as exc:
            db.fail_run(run_id, public_error(exc))

    @app.post('/api/projects/{project_id}/stages/{stage}/generate', status_code=202)
    def generate(project_id: str, stage: Stage, body: GenerateRequest, background: BackgroundTasks,
                 user=Depends(current_user)):
        try:
            run_id, project, context, previous = db.prepare_run(project_id, user['id'], stage, STAGES,
                                                                 body.feedback, config['daily_limit'])
        except DatabaseError as exc:
            fail(exc)
        background.add_task(generate_job, run_id, project, stage, context, body.feedback, previous)
        return {'id': run_id, 'status': 'running', 'stage': stage}

    @app.post('/api/projects/{project_id}/stages/{stage}/accept')
    def accept(project_id: str, stage: Stage, body: AcceptRequest, user=Depends(current_user)):
        try:
            return db.accept(project_id, user['id'], stage, STAGES, body.artifact_id, body.decision, body.revised_idea)
        except DatabaseError as exc:
            fail(exc)

    @app.get('/api/projects/{project_id}/export')
    def export(project_id: str, user=Depends(current_user)):
        try:
            project = db.detail(project_id, user['id'])
        except DatabaseError as exc:
            fail(exc)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('project-state.json', dump(project))
            archive.writestr('README.md', f'# {project["title"]}\n\nMode: {project["mode"]}\n\nCurrent files include drafts; project-state.json records approval and validity. History preserves all versions.\nGenerated HTML is a prototype with potentially executable scripts; preview inside the app sandbox.\n')
            for artifact in project['artifacts']:
                status = 'Accepted' if artifact['approved_at'] else 'Draft'
                markdown = f'> {status} | v{artifact["version"]} | {project["mode"]}\n\n' + artifact['content']['markdown']
                historical = f'history/{artifact["stage"]}/v{artifact["version"]}'
                archive.writestr(historical + '.json', dump(artifact))
                archive.writestr(historical + '.md', markdown)
                if not artifact['valid']:
                    continue
                archive.writestr(FILENAMES[artifact['stage']], markdown)
                if artifact['stage'] == 'research': archive.writestr('sources.json', dump(artifact['metadata']))
                if artifact['stage'] == 'prototype': archive.writestr('04-prototype/index.html', artifact['content']['html'])
                if artifact['stage'] == 'architecture': archive.writestr('architecture.mmd', artifact['content']['mermaid'])
                if artifact['stage'] == 'functions':
                    output = io.StringIO(newline='')
                    writer = csv.writer(output)
                    writer.writerow(['ID', 'Function', 'Requirement', 'Tier', 'Dependencies', 'Low days', 'Likely days', 'High days', 'Daily rate', 'Currency', 'Low cost', 'Likely cost', 'High cost'])
                    rate = artifact['content']['daily_rate']
                    def cell(value):
                        value = str(value)
                        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
                    for function in artifact['content']['functions']:
                        days = [function[key] for key in ('low_days', 'likely_days', 'high_days')]
                        writer.writerow([cell(value) for value in [function['id'], function['name'], function['requirement'], function['tier'], ', '.join(function['dependencies']), *days, rate, artifact['content']['currency'], *[round(day * rate, 2) for day in days]]])
                    archive.writestr('03-functional-list.csv', '\ufeff' + output.getvalue())
        return Response(buffer.getvalue(), media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="brainstorm-{project_id[:8]}.zip"'})

    return app


app = create_app()
