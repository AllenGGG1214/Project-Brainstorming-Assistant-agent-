"""Tools the agent may call, plus the per-run context they operate on.

Every tool is scoped to a single project whose ownership was verified before
the run started; the model can never pass a project id.
"""
import json
from dataclasses import dataclass, field
from typing import Callable

from ..rag import store

MAX_RESULT_CHARS = 1800


@dataclass
class AgentContext:
    """Per-run state shared by the harness and its tools."""
    project_id: str
    load_chunks: Callable[[], list] = lambda: []
    embed_query: Callable[[str], list] | None = None
    record: Callable[[str, dict, int], None] = lambda kind, payload, tokens=0: None
    retrieved: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    _chunks: list | None = None

    def chunks(self):
        if self._chunks is None:
            self._chunks = self.load_chunks()
        return self._chunks

    @property
    def has_documents(self):
        return bool(self.chunks())

    def search(self, query, k=5):
        vector = None
        if self.embed_query and any(c.get('embedding') for c in self.chunks()):
            vector = self.embed_query(query)
        results = store.search(self.chunks(), query, k=max(1, min(int(k or 5), 8)), query_embedding=vector)
        for item in results:
            self.retrieved[item['ref']] = item
        return results


def _search_documents(ctx, args):
    results = ctx.search(args['query'], args.get('k') or 5)
    return {'results': [{'ref': r['ref'], 'location': r['location'], 'score': r['score'],
                         'text': r['text'][:MAX_RESULT_CHARS]} for r in results]}


def _read_chunk(ctx, args):
    wanted = args['ref']
    for chunk in ctx.chunks():
        if store.ref(chunk['document_id'], chunk['ordinal']) == wanted:
            item = {'ref': wanted, 'filename': chunk['filename'], 'location': chunk['location'], 'text': chunk['text'], 'score': 1.0}
            ctx.retrieved[wanted] = item
            return {'ref': wanted, 'location': chunk['location'], 'text': chunk['text'][:MAX_RESULT_CHARS * 2]}
    return {'error': 'Unknown reference. Use a ref returned by search_documents.'}


def _note_finding(ctx, args):
    refs = [r for r in args.get('refs', []) if r in ctx.retrieved]
    ctx.notes.append({'finding': args['finding'][:1000], 'refs': refs})
    return {'saved': True, 'verified_refs': refs}


def _schema(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


TOOLS = {
    'search_documents': {
        'description': "Semantic + keyword search over the user's uploaded documents and code for this project. "
                       'Returns chunks with a ref like doc:<id>#<n> that you can cite.',
        'parameters': _schema({'query': {'type': 'string', 'description': 'What to look for.'},
                               'k': {'type': 'integer', 'description': 'Number of results (1-8).'}}, ['query', 'k']),
        'handler': _search_documents,
    },
    'read_document_chunk': {
        'description': 'Read the full text of one chunk returned by search_documents.',
        'parameters': _schema({'ref': {'type': 'string'}}, ['ref']),
        'handler': _read_chunk,
    },
    'note_finding': {
        'description': 'Record a finding you will rely on in the final answer, with the doc refs that support it.',
        'parameters': _schema({'finding': {'type': 'string'}, 'refs': {'type': 'array', 'items': {'type': 'string'}}},
                              ['finding', 'refs']),
        'handler': _note_finding,
    },
}


def tool_specs(names):
    return [{'type': 'function', 'name': n, 'description': TOOLS[n]['description'],
             'parameters': TOOLS[n]['parameters'], 'strict': True} for n in names]


def run_tool(ctx, name, raw_arguments):
    if name not in TOOLS:
        return {'error': f'Unknown tool {name}.'}
    try:
        args = json.loads(raw_arguments or '{}')
    except json.JSONDecodeError:
        return {'error': 'Arguments were not valid JSON.'}
    try:
        return TOOLS[name]['handler'](ctx, args)
    except (KeyError, TypeError, ValueError) as exc:
        return {'error': f'Invalid arguments: {type(exc).__name__}.'}
