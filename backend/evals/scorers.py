"""Deterministic scorers for one evaluated project. Each returns a value in [0, 1] or a raw number."""
import re

from app.rag.store import REF_PATTERN
from app.schemas import OUTPUTS, STAGES, Starter, safe_relative_path, validate_traceability

# Metrics that must stay at 1.0; CI fails below these thresholds.
THRESHOLDS = {'stages_completed': 1.0, 'schema_valid': 1.0, 'traceability': 1.0, 'web_citations_valid': 1.0,
              'doc_citations_valid': 1.0, 'doc_grounding': 1.0, 'starter_safe': 1.0, 'mvp_covered': 1.0}


def _active(detail):
    return {a['stage']: a for a in detail['artifacts'] if a['valid']}


def score_project(detail, chunk_refs, has_docs):
    active = _active(detail)
    contents = {s: a['content'] for s, a in active.items()}
    scores = {'stages_completed': len(active) / len(STAGES)}

    valid = 0
    for stage, content in contents.items():
        try:
            OUTPUTS[stage].model_validate(content)
            valid += 1
        except Exception:
            pass
    scores['schema_valid'] = valid / max(len(contents), 1)

    traced, checked = 0, 0
    for stage in ('prototype', 'architecture', 'starter'):
        if stage in contents and 'functions' in contents:
            checked += 1
            try:
                validate_traceability(stage, OUTPUTS[stage].model_validate(contents[stage]), contents)
                traced += 1
            except Exception:
                pass
    scores['traceability'] = traced / checked if checked else 0.0

    research = active.get('research')
    if research and research['metadata'].get('mode') == 'live':
        known = {s['url'] for s in research['metadata'].get('sources', [])}
        cited = set(re.findall(r'\]\((https?://[^\s]+?)\)', research['content']['markdown']))
        scores['web_citations_valid'] = 1.0 if cited and cited <= known else 0.0
    else:
        scores['web_citations_valid'] = 1.0  # demo mode performs no web research

    cited_docs = set()
    for artifact in active.values():
        cited_docs |= set(REF_PATTERN.findall(str(artifact['content'])))
    scores['doc_citations_valid'] = 1.0 if cited_docs <= chunk_refs else 0.0
    scores['doc_grounding'] = (1.0 if cited_docs else 0.0) if has_docs else 1.0

    starter = contents.get('starter')
    if starter:
        model = Starter.model_validate(starter)
        scores['starter_safe'] = 1.0 if all(safe_relative_path(f.path) for f in model.files) else 0.0
        mvp = {f['id'] for f in contents['functions']['functions'] if f['tier'] == 'MVP'}
        used = {i for f in model.files for i in f.function_ids} | {i for t in model.tasks for i in t.function_ids}
        scores['mvp_covered'] = len(mvp & used) / max(len(mvp), 1)
        scores['starter_files'] = len(model.files)
    else:
        scores['starter_safe'] = scores['mvp_covered'] = 0.0

    steps = [s for r in detail['runs'] for s in r.get('steps', [])]
    scores['agent_steps'] = sum(1 for s in steps if s['kind'] == 'model')
    scores['tool_calls'] = sum(1 for s in steps if s['kind'] == 'tool_call')
    scores['tokens'] = sum(int(u.get('total_tokens') or 0) for a in active.values() for u in a['metadata'].get('usage', []))
    return scores
