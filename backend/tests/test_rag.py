import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.provider import Provider
from app.rag.ingest import IngestError, chunk, extract
from app.rag.store import search

NOTES = b"""# Existing stack
We already run a Django backend with PostgreSQL and Celery workers.
Authentication uses university single sign-on (SAML).

# Pain point
Students lose track of which papers they read for each course.
"""


def make_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buffer.getvalue()


def test_chunking_keeps_line_ranges_and_overlap():
    text = '\n'.join(f'line {i} ' + 'x' * 60 for i in range(200))
    pieces = chunk('notes.md', text, limit=1000, overlap=2)
    assert len(pieces) > 5
    assert pieces[0]['location'].startswith('notes.md:1-')
    first_end = int(pieces[0]['location'].split('-')[1])
    second_start = int(pieces[1]['location'].split(':')[1].split('-')[0])
    assert second_start == first_end - 1  # two overlapping lines


def test_zip_skips_traversal_vendored_and_binary_files():
    data = make_zip({'../evil.py': 'print(1)', '/abs.md': 'x', 'node_modules/lib.js': 'x', 'logo.png': b'\x89PNG\x00\x00',
                     'src/app.py': 'def main():\n    return 1\n', 'README.md': '# Repo'})
    kind, files = extract('repo.zip', data)
    assert kind == 'archive'
    assert sorted(path for path, _ in files) == ['README.md', 'src/app.py']


def test_unsupported_and_empty_files_are_rejected():
    with pytest.raises(IngestError):
        extract('photo.png', b'\x89PNG\x00')
    with pytest.raises(IngestError):
        extract('empty.md', b'   ')
    with pytest.raises(IngestError):
        extract('repo.zip', make_zip({'image.png': b'\x00'}))


def test_keyword_search_ranks_relevant_chunk_first():
    chunks = [{'document_id': 'a' * 32, 'ordinal': i, 'filename': 'n.md', 'location': f'n.md:{i}', 'text': t, 'embedding': None}
              for i, t in enumerate(['Celery workers and PostgreSQL', 'Students lose track of papers', 'Unrelated cooking recipe'])]
    results = search(chunks, 'which papers did students read', k=2)
    assert results[0]['text'] == 'Students lose track of papers'
    assert results[0]['ref'] == f"doc:{'a' * 32}#1"


def test_hybrid_search_uses_embeddings_when_present():
    chunks = [{'document_id': 'b' * 32, 'ordinal': i, 'filename': 'n.md', 'location': 'n.md', 'text': t, 'embedding': e}
              for i, (t, e) in enumerate([('alpha', [1.0, 0.0]), ('beta', [0.0, 1.0])])]
    assert search(chunks, 'zzz', k=1, query_embedding=[0.0, 1.0])[0]['text'] == 'beta'


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'rag.db', Provider('', 'test-model'))) as c:
        yield c


def project(client):
    return client.post('/api/projects', json={'title': 'Reading tracker', 'idea': 'Help students track which papers they read for each course.', 'mode': 'demo'}).json()['id']


def test_upload_list_and_delete_documents(client):
    pid = project(client)
    r = client.post(f'/api/projects/{pid}/documents', files={'file': ('notes.md', NOTES, 'text/markdown')})
    assert r.status_code == 201, r.text
    docs = r.json()['documents']
    assert docs[0]['filename'] == 'notes.md' and docs[0]['chunk_count'] >= 1 and docs[0]['embedded'] == 0
    zipped = make_zip({'repo/app.py': 'print("hi")', 'repo/README.md': '# Hi'})
    assert client.post(f'/api/projects/{pid}/documents', files={'file': ('repo.zip', zipped, 'application/zip')}).status_code == 201
    assert client.post(f'/api/projects/{pid}/documents', files={'file': ('x.exe', b'MZ\x00', 'application/octet-stream')}).status_code == 422
    r = client.post(f"/api/projects/{pid}/documents/{docs[0]['id']}/delete")
    assert r.status_code == 200 and len(r.json()['documents']) == 1


def test_demo_run_retrieves_and_cites_uploaded_chunks(client):
    pid = project(client)
    client.post(f'/api/projects/{pid}/documents', files={'file': ('notes.md', NOTES, 'text/markdown')})
    assert client.post(f'/api/projects/{pid}/stages/organize/generate', json={}).status_code == 202
    detail = client.get(f'/api/projects/{pid}').json()
    run = detail['runs'][0]
    assert run['status'] == 'succeeded'
    assert [s['kind'] for s in run['steps']] == ['tool_call', 'tool_result', 'final']
    artifact = next(a for a in detail['artifacts'] if a['stage'] == 'organize')
    assert artifact['metadata']['documents_cited']
    assert artifact['metadata']['documents_cited'][0] in artifact['content']['markdown']


def test_documents_are_private_between_accounts(tmp_path):
    settings = {'auth_required': True, 'allow_signups': True, 'invite_code': 'invite-123'}
    with TestClient(create_app(tmp_path / 'private.db', Provider('', 'test'), settings)) as client:
        client.post('/api/auth/register', json={'email': 'a@example.com', 'password': 'a-long-password', 'invite_code': 'invite-123'})
        pid = project(client)
        doc = client.post(f'/api/projects/{pid}/documents', files={'file': ('notes.md', NOTES, 'text/markdown')}).json()['documents'][0]
        client.post('/api/auth/logout')
        client.cookies.clear()
        client.post('/api/auth/register', json={'email': 'b@example.com', 'password': 'b-long-password', 'invite_code': 'invite-123'})
        assert client.post(f'/api/projects/{pid}/documents', files={'file': ('x.md', b'hello there', 'text/markdown')}).status_code == 404
        assert client.post(f"/api/projects/{pid}/documents/{doc['id']}/delete").status_code == 404
