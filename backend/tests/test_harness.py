"""Agent harness contract tests. OpenAI is faked with httpx.MockTransport."""
import json
from unittest.mock import patch

import httpx
import pytest
from openai import OpenAI

from app.agent.harness import Budget
from app.agent.tools import AgentContext
from app.provider import Provider

DOC = 'c' * 32
CHUNKS = [{'document_id': DOC, 'ordinal': 0, 'filename': 'stack.md', 'location': 'stack.md:1-3',
           'text': 'We use Django and PostgreSQL. Auth is university SSO.', 'embedding': None}]
PROJECT = {'id': 'p', 'mode': 'live', 'title': 'Tracker', 'idea': 'Track papers read per course', 'constraints': ''}
BRIEF = {'markdown': '# Brief\nThe team already runs Django (doc:%s#0).' % DOC, 'assumptions': ['a'], 'search_terms': ['b']}


def usage(n=100):
    return {'input_tokens': n, 'output_tokens': 0, 'total_tokens': n,
            'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}}


def reply(output, tokens=100, rid='resp'):
    return {'id': rid, 'created_at': 1, 'model': 'gpt-5.5', 'object': 'response', 'status': 'completed', 'output': output,
            'parallel_tool_calls': True, 'tool_choice': 'auto', 'tools': [], 'usage': usage(tokens)}


def call(name, args, cid):
    return {'type': 'function_call', 'id': 'fc_' + cid, 'call_id': cid, 'name': name, 'arguments': json.dumps(args), 'status': 'completed'}


def message(text):
    return {'id': 'msg', 'type': 'message', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}


def context():
    steps = []
    ctx = AgentContext(project_id='p', load_chunks=lambda: list(CHUNKS), record=lambda k, p, t=0: steps.append((k, p)))
    return ctx, steps


def fake_client(script, calls):
    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json=script(len(calls), body))
    return OpenAI(api_key='k', http_client=httpx.Client(transport=httpx.MockTransport(handle)))


def test_tool_loop_executes_tools_and_feeds_results_back():
    calls = []
    def script(n, body):
        if n == 1:
            return reply([call('search_documents', {'query': 'existing stack', 'k': 3}, 'c1')])
        if n == 2:
            return reply([call('note_finding', {'finding': 'Uses Django', 'refs': [f'doc:{DOC}#0', 'doc:fake#9']}, 'c2')])
        if n == 3:
            return reply([message('Found the stack.')])
        return reply([message(json.dumps(BRIEF))])
    ctx, steps = context()
    with patch('app.provider.OpenAI', return_value=fake_client(script, calls)):
        result, meta = Provider('k', 'gpt-5.5').generate('organize', PROJECT, {}, '', None, ctx)
    assert len(calls) == 4
    assert {t['name'] for t in calls[0]['tools']} == {'search_documents', 'read_document_chunk', 'note_finding'}
    outputs = [i for i in calls[1]['input'] if i.get('type') == 'function_call_output']
    assert 'untrusted_data' in outputs[0]['output'] and 'Django' in outputs[0]['output']
    assert ctx.notes == [{'finding': 'Uses Django', 'refs': [f'doc:{DOC}#0']}]  # fake ref dropped
    assert f'doc:{DOC}#0' in calls[3]['input']  # ledger reaches the final structured call
    assert meta['documents_cited'] == [f'doc:{DOC}#0']
    assert meta['agent']['steps'] == 3 and meta['agent']['tool_calls'] == 2
    kinds = [k for k, _ in steps]
    assert kinds.count('tool_call') == 2 and kinds[-1] == 'final' and 'budget' in kinds


def test_step_budget_stops_a_looping_agent():
    calls = []
    def script(n, body):
        if body.get('text', {}).get('format', {}).get('type') == 'json_schema':
            return reply([message(json.dumps(BRIEF))])
        return reply([call('search_documents', {'query': f'Django stack {n}', 'k': 1}, f'c{n}')])
    ctx, _ = context()
    with patch('app.provider.OpenAI', return_value=fake_client(script, calls)):
        _, meta = Provider('k', 'gpt-5.5', Budget(max_steps=3)).generate('organize', PROJECT, {}, '', None, ctx)
    assert meta['agent']['stopped_by'] == 'step_budget'
    assert len(calls) == 4  # 3 loop steps + final structured call


def test_token_budget_stops_the_loop():
    calls = []
    def script(n, body):
        if body.get('text', {}).get('format', {}).get('type') == 'json_schema':
            return reply([message(json.dumps(BRIEF))])
        return reply([call('search_documents', {'query': 'Django', 'k': 1}, f'c{n}')], tokens=600)
    ctx, _ = context()
    with patch('app.provider.OpenAI', return_value=fake_client(script, calls)):
        _, meta = Provider('k', 'gpt-5.5', Budget(max_tokens=1000)).generate('organize', PROJECT, {}, '', None, ctx)
    assert meta['agent']['stopped_by'] == 'token_budget' and meta['agent']['steps'] == 2


def test_fabricated_document_citation_is_rejected():
    calls = []
    fabricated = dict(BRIEF, markdown='# Brief\nSee doc:%s#7.' % ('d' * 32))
    def script(n, body):
        if n == 1:
            return reply([message('No tools needed.')])
        return reply([message(json.dumps(fabricated))])
    ctx, _ = context()
    with patch('app.provider.OpenAI', return_value=fake_client(script, calls)), pytest.raises(ValueError, match='self-corrections.*not retrieved'):
        Provider('k', 'gpt-5.5').generate('organize', PROJECT, {}, '', None, ctx)
    assert len(calls) == 4  # loop step + first attempt + 2 repairs


def test_agent_repairs_its_own_invalid_output():
    calls = []
    fabricated = dict(BRIEF, markdown='# Brief\nSee doc:%s#7.' % ('d' * 32))
    def script(n, body):
        if n == 1:
            return reply([call('search_documents', {'query': 'Django', 'k': 1}, 'c1')])
        if n == 2:
            return reply([message('Done.')])
        return reply([message(json.dumps(fabricated if n == 3 else BRIEF))])
    ctx, steps = context()
    with patch('app.provider.OpenAI', return_value=fake_client(script, calls)):
        result, meta = Provider('k', 'gpt-5.5').generate('organize', PROJECT, {}, '', None, ctx)
    assert len(calls) == 4 and len(meta['repairs']) == 1 and 'not retrieved' in meta['repairs'][0]
    assert 'FAILED VALIDATION' in calls[3]['input'] and 'd' * 32 in calls[3]['input']
    assert meta['documents_cited'] == [f'doc:{DOC}#0'] and len(meta['usage']) == 4
    assert [k for k, _ in steps].count('repair') == 1


def test_unknown_tool_and_bad_arguments_return_errors_not_crashes():
    from app.agent.tools import run_tool
    ctx, _ = context()
    assert 'error' in run_tool(ctx, 'delete_everything', '{}')
    assert 'error' in run_tool(ctx, 'search_documents', 'not json')
    assert 'error' in run_tool(ctx, 'read_document_chunk', json.dumps({'ref': 'doc:nope#1'}))


def test_no_documents_and_no_web_stage_skips_the_loop():
    calls = []
    ctx = AgentContext(project_id='p')
    def script(n, body):
        return reply([message(json.dumps({**BRIEF, 'markdown': '# Brief'}))])
    with patch('app.provider.OpenAI', return_value=fake_client(script, calls)):
        _, meta = Provider('k', 'gpt-5.5').generate('organize', PROJECT, {}, '', None, ctx)
    assert len(calls) == 1 and meta['agent']['stopped_by'] == 'no_tools'
