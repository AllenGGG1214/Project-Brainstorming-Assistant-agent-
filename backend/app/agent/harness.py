"""Agent runtime harness: a bounded tool-calling loop over the Responses API.

The model chooses which tool to call next; the harness executes it, enforces
budgets (steps, tokens, wall-clock time), records every step for the trace,
and collects an evidence ledger (web sources + retrieved document chunks).
The final artifact is produced afterwards by a strict structured-output call,
so all existing validation still applies.
"""
import json
import time
from dataclasses import dataclass

from .tools import run_tool, tool_specs

WEB_STAGES = {'research', 'architecture', 'starter'}
DOC_TOOLS = ['search_documents', 'read_document_chunk', 'note_finding']


@dataclass
class Budget:
    max_steps: int = 8
    max_tool_calls: int = 16
    max_tokens: int = 80_000
    max_seconds: float = 240.0


def plan_tools(stage, ctx):
    """Which tools the agent gets for this stage. Empty means no loop is needed."""
    names = list(DOC_TOOLS) if ctx is not None and ctx.has_documents else []
    hosted = [{'type': 'web_search'}] if stage in WEB_STAGES else []
    return hosted, names


def _usage(response):
    usage = response.usage.model_dump() if getattr(response, 'usage', None) else {}
    return usage, int(usage.get('total_tokens') or 0)


def run_agent(client, model, stage, instructions, prompt, ctx, budget=None, extract_evidence=None):
    budget = budget or Budget()
    hosted, names = plan_tools(stage, ctx)
    tools = hosted + tool_specs(names)
    findings = {'sources': [], 'queries': [], 'citations': [], 'search_text': '', 'usage': [], 'response_ids': [],
                'steps': 0, 'tool_calls': 0, 'tokens': 0, 'stopped_by': 'complete'}
    if not tools:
        findings['stopped_by'] = 'no_tools'
        return findings
    record = ctx.record if ctx else (lambda *a, **k: None)
    items = [{'role': 'user', 'content': prompt}]
    seen_sources = {}
    started = time.monotonic()
    for step in range(budget.max_steps):
        kwargs = dict(model=model, store=False, tools=tools, instructions=instructions, input=items, max_output_tokens=6000)
        if hosted:
            kwargs['include'] = ['web_search_call.action.sources']
        if step == 0 and stage == 'research':
            kwargs['tool_choice'] = 'required'  # research must gather evidence before answering
        response = client.responses.create(**kwargs)
        usage, tokens = _usage(response)
        findings['usage'].append(usage)
        findings['response_ids'].append(response.id)
        findings['steps'] += 1
        findings['tokens'] += tokens
        if extract_evidence:
            evidence = extract_evidence(response)
            for source in evidence['sources']:
                seen_sources[source['url']] = source
            findings['queries'].extend(q for q in evidence['queries'] if q not in findings['queries'])
            findings['citations'].extend(evidence['citations'])
            for query in evidence['queries']:
                record('tool_call', {'tool': 'web_search', 'arguments': {'query': query}}, 0)
            if evidence['sources']:
                record('tool_result', {'tool': 'web_search', 'summary': f"{len(evidence['sources'])} sources",
                                       'sources': [s['url'] for s in evidence['sources']][:10]}, 0)
        output = [item.model_dump(exclude_none=True) if hasattr(item, 'model_dump') else item for item in response.output]
        calls = [item for item in output if item.get('type') == 'function_call']
        text = response.output_text or ''
        record('model', {'step': step + 1, 'text': text[:1200], 'function_calls': [c['name'] for c in calls]}, tokens)
        if text:
            findings['search_text'] = (findings['search_text'] + '\n\n' + text).strip()
        if not calls:
            break
        # Reasoning items are not replayed (store=False); messages, searches and calls are.
        items.extend(item for item in output if item.get('type') != 'reasoning')
        for call in calls:
            if findings['tool_calls'] >= budget.max_tool_calls:
                result = {'error': 'Tool-call budget exhausted. Answer with what you have.'}
            else:
                findings['tool_calls'] += 1
                result = run_tool(ctx, call['name'], call.get('arguments'))
            record('tool_call', {'tool': call['name'], 'arguments': _safe_json(call.get('arguments'))}, 0)
            record('tool_result', {'tool': call['name'], 'summary': _summarise(result)}, 0)
            items.append({'type': 'function_call_output', 'call_id': call['call_id'],
                          'output': json.dumps({'untrusted_data': result}, ensure_ascii=False)})
        if findings['tokens'] >= budget.max_tokens:
            findings['stopped_by'] = 'token_budget'
            break
        if time.monotonic() - started >= budget.max_seconds:
            findings['stopped_by'] = 'time_budget'
            break
    else:
        findings['stopped_by'] = 'step_budget'
    findings['sources'] = list(seen_sources.values())
    record('budget', {'steps': findings['steps'], 'tool_calls': findings['tool_calls'],
                      'tokens': findings['tokens'], 'stopped_by': findings['stopped_by']}, 0)
    return findings


def _safe_json(raw):
    try:
        return json.loads(raw or '{}')
    except json.JSONDecodeError:
        return {'raw': str(raw)[:200]}


def _summarise(result):
    if 'results' in result:
        return f"{len(result['results'])} chunks: " + ', '.join(r['location'] for r in result['results'][:5])
    if 'error' in result:
        return result['error']
    if 'location' in result:
        return f"read {result['location']}"
    return 'saved' if result.get('saved') else json.dumps(result)[:200]
