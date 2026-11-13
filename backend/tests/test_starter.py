import pytest
from pydantic import ValidationError

from app.schemas import Starter, safe_relative_path, validate_traceability

CONTEXT = {'functions': {'functions': [{'id': 'FL-001', 'tier': 'MVP'}, {'id': 'FL-002', 'tier': 'MVP'}, {'id': 'FL-003', 'tier': 'Stretch'}]}}


def starter(**overrides):
    data = dict(markdown='# Starter', stack='Python', run_instructions='run it',
                files=[{'path': 'README.md', 'purpose': 'docs', 'content': '# Hi', 'function_ids': []},
                       {'path': 'app/main.py', 'purpose': 'api', 'content': 'print(1)', 'function_ids': ['FL-001']}],
                tasks=[{'id': 'T-001', 'title': 'Build list', 'function_ids': ['FL-002'], 'done_when': 'test passes'}])
    data.update(overrides)
    return data


def test_valid_starter_passes_traceability():
    validate_traceability('starter', Starter.model_validate(starter()), CONTEXT)


@pytest.mark.parametrize('path', ['../escape.py', '/etc/passwd', 'C:/x.py', 'a\\b.py', 'a//b.py', './a.py', 'a/../b.py'])
def test_unsafe_paths_rejected(path):
    assert not safe_relative_path(path)
    files = starter()['files'] + [{'path': path, 'purpose': 'x', 'content': '', 'function_ids': []}]
    with pytest.raises(ValidationError):
        Starter.model_validate(starter(files=files))


def test_readme_required_and_secrets_and_size_rejected():
    with pytest.raises(ValidationError):
        Starter.model_validate(starter(files=[{'path': 'main.py', 'purpose': 'x', 'content': '', 'function_ids': []}]))
    leaked = starter()['files'] + [{'path': '.env', 'purpose': 'x', 'content': 'OPENAI_API_KEY=sk-' + 'a' * 40, 'function_ids': []}]
    with pytest.raises(ValidationError, match='secret'):
        Starter.model_validate(starter(files=leaked))
    big = starter()['files'] + [{'path': 'big.txt', 'purpose': 'x', 'content': 'x' * 210_000, 'function_ids': []}]
    with pytest.raises(ValidationError, match='too large'):
        Starter.model_validate(starter(files=big))


def test_mvp_coverage_and_unknown_ids_enforced():
    missing = Starter.model_validate(starter(tasks=[{'id': 'T-001', 'title': 't', 'function_ids': ['FL-003'], 'done_when': 'x'}]))
    with pytest.raises(ValueError, match='MVP'):
        validate_traceability('starter', missing, CONTEXT)
    unknown = Starter.model_validate(starter(tasks=[{'id': 'T-001', 'title': 't', 'function_ids': ['FL-002', 'FL-999'], 'done_when': 'x'}]))
    with pytest.raises(ValueError, match='existing'):
        validate_traceability('starter', unknown, CONTEXT)
