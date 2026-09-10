import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from openai import OpenAI

from app.provider import Provider


def response(text=None, sources=None):
    output = []
    if sources is not None:
        output.append({'id': 'ws_1', 'type': 'web_search_call', 'status': 'completed', 'action': {'type': 'search', 'queries': ['student paper notes'], 'sources': sources}})
    output.append({'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [{'type': 'output_text', 'text': text or 'Search results [Example](https://example.org)', 'annotations': []}]})
    return {'id': 'resp_1', 'created_at': 100, 'model': 'gpt-5.5', 'object': 'response', 'status': 'completed', 'output': output, 'parallel_tool_calls': True, 'tool_choice': 'auto', 'tools': [], 'usage': {'input_tokens': 20, 'output_tokens': 30, 'total_tokens': 50, 'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}}}


PROJECT = {'id': 'p', 'mode': 'live', 'title': 'Research demo', 'idea': 'A paper reading application', 'constraints': '4 weeks'}


def test_sdk_search_then_strict_parse_contract():
    calls = []
    structured = {'markdown': '# Research\n\n[Example](https://example.org) provides a comparable function.', 'recommendation': 'GO', 'rationale': 'Contract test only', 'comparisons': [{'name': 'Example', 'overlap': 'Comparable', 'difference': 'Unverified', 'evidence': 'Verified', 'source_urls': ['https://example.org']}], 'uncertainty': ['Unverified']}
    def handle(request):
        assert request.url.path == '/v1/responses'
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json=response(sources=[{'type': 'url', 'url': 'https://example.org'}]) if len(calls) == 1 else response(json.dumps(structured)))
    client = OpenAI(api_key='test-key', http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    with patch('app.provider.OpenAI', return_value=client):
        result, meta = Provider('test-key', 'gpt-5.5').generate('research', PROJECT, {}, '', None)
    assert result['recommendation'] == 'GO'
    assert len(calls) == 2
    assert calls[0]['tool_choice'] == 'required'
    assert calls[0]['tools'] == [{'type': 'web_search'}]
    assert calls[0]['include'] == ['web_search_call.action.sources']
    assert calls[1]['text']['format']['type'] == 'json_schema'
    assert calls[1]['text']['format']['strict'] is True
    assert 'https://example.org' in calls[1]['input']
    assert all(c['store'] is False for c in calls)
    assert meta['sources'][0]['url'] == 'https://example.org'
    assert len(meta['usage']) == 2


def test_search_without_sources_fails_closed():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=response('No evidence', sources=[]))
    client = OpenAI(api_key='test-key', http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    with patch('app.provider.OpenAI', return_value=client), pytest.raises(ValueError, match='sources'):
        Provider('test-key', 'gpt-5.5').generate('research', PROJECT, {}, '', None)
    assert len(calls) == 1


def test_refusal_is_not_saved_as_success():
    def handle(request):
        data = response()
        data['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'Cannot help'}]
        return httpx.Response(200, json=data)
    client = OpenAI(api_key='test-key', http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    with patch('app.provider.OpenAI', return_value=client), pytest.raises(ValueError, match='complete structured'):
        Provider('test-key', 'gpt-5.5').generate('organize', PROJECT, {}, '', None)
