from fastapi.testclient import TestClient

from app.main import create_app
from app.provider import Provider


def production_app(path, **overrides):
    settings = {'auth_required': True, 'allow_signups': True, 'invite_code': 'invite-only',
                'cookie_secure': False, 'daily_limit': 20,
                'trusted_hosts': ['testserver'], 'cors_origins': ['http://testserver']}
    settings.update(overrides)
    return create_app(path, Provider('', 'test-model'), settings)


def register(client, email='owner@example.com'):
    return client.post('/api/auth/register', json={'email': email, 'password': 'a strong password', 'invite_code': 'invite-only'})


def test_invite_registration_login_and_logout(tmp_path):
    with TestClient(production_app(tmp_path / 'auth.db')) as client:
        assert client.get('/api/projects').status_code == 401
        assert client.post('/api/auth/register', json={'email': 'owner@example.com', 'password': 'a strong password', 'invite_code': 'wrong'}).status_code == 403
        assert register(client).status_code == 201
        assert client.get('/api/auth/status').json()['user']['email'] == 'owner@example.com'
        assert client.post('/api/auth/logout', json={}).status_code == 204
        assert client.get('/api/projects').status_code == 401
        assert client.post('/api/auth/login', json={'email': 'owner@example.com', 'password': 'wrong'}).status_code == 401
        assert client.post('/api/auth/login', json={'email': 'OWNER@example.com', 'password': 'a strong password'}).status_code == 200


def test_projects_are_private_between_accounts(tmp_path):
    app = production_app(tmp_path / 'private.db')
    with TestClient(app) as owner:
        assert register(owner).status_code == 201
        project = owner.post('/api/projects', json={'title': 'Private idea', 'idea': 'A private project idea for testing access.', 'mode': 'demo'}).json()
        with TestClient(app) as second:
            assert register(second, 'second@example.com').status_code == 201
            assert second.get(f'/api/projects/{project["id"]}').status_code == 404
            assert second.get(f'/api/projects/{project["id"]}/export').status_code == 404
            assert second.get('/api/projects').json() == []
