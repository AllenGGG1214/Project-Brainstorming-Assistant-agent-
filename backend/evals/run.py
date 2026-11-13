"""Evaluation harness: run sample ideas through the real API and score the results.

    python -m evals.run --mode demo            # free, deterministic; used in CI
    python -m evals.run --mode live --ideas 2  # real agent; uses OPENAI_API_KEY and costs credits
    python -m evals.run --mode live --judge    # add an LLM-judge quality rubric

Writes evals/reports/<timestamp>.json and .md and compares with the previous report.
Exit code 1 if any deterministic metric falls below its threshold.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from fastapi.testclient import TestClient

from app.main import create_app
from app.provider import Provider
from app.rag.store import ref
from app.schemas import STAGES

from .scorers import THRESHOLDS, score_project

HERE = Path(__file__).resolve().parent
REPORTS = HERE / 'reports'


def run_idea(client, db, idea, mode):
    project = client.post('/api/projects', json={'title': idea['title'], 'idea': idea['idea'],
                                                 'constraints': idea.get('constraints', ''), 'mode': mode}).json()
    pid = project['id']
    for doc in idea.get('docs', []):
        r = client.post(f'/api/projects/{pid}/documents', files={'file': (doc['filename'].split('/')[-1], doc['content'].encode(), 'text/plain')})
        if r.status_code != 201:
            raise RuntimeError(f"upload failed: {r.text}")
    timings, error = {}, None
    for stage in STAGES:
        started = time.monotonic()
        r = client.post(f'/api/projects/{pid}/stages/{stage}/generate', json={})
        detail = client.get(f'/api/projects/{pid}').json()
        timings[stage] = round(time.monotonic() - started, 2)
        run = detail['runs'][0]
        if r.status_code != 202 or run['status'] != 'succeeded':
            error = f"{stage}: {run.get('error') or r.text}"
            break
        artifact = next(a for a in detail['artifacts'] if a['stage'] == stage and a['valid'])
        body = {'artifact_id': artifact['id'], 'decision': 'GO' if stage == 'research' else None}
        if client.post(f'/api/projects/{pid}/stages/{stage}/accept', json=body).status_code != 200:
            error = f'{stage}: accept failed'
            break
    detail = client.get(f'/api/projects/{pid}').json()
    chunk_refs = {ref(c['document_id'], c['ordinal']) for c in db.project_chunks(pid)}
    scores = score_project(detail, chunk_refs, bool(idea.get('docs')))
    scores['seconds'] = round(sum(timings.values()), 2)
    return {'id': idea['id'], 'error': error, 'scores': scores, 'timings': timings, 'detail': detail}


JUDGE_PROMPT = '''You are grading a generated project plan for an individual builder. Score 1-5 each:
specificity (concrete to THIS idea, not generic), feasibility (MVP fits the stated constraints),
grounding (claims tied to cited sources or uploaded documents; no invented facts),
starter_usefulness (the starter repo is a sensible, runnable skeleton for the architecture).
Be strict; 3 means acceptable. Return brief reasons.'''


def judge(provider, result):
    from openai import OpenAI
    from pydantic import BaseModel

    class Grade(BaseModel):
        specificity: int
        feasibility: int
        grounding: int
        starter_usefulness: int
        reasons: str

    active = {a['stage']: a['content'] for a in result['detail']['artifacts'] if a['valid']}
    payload = {stage: {k: v for k, v in content.items() if k != 'html'} for stage, content in active.items()}
    with OpenAI(api_key=provider.api_key, timeout=180, max_retries=0) as client:
        response = client.responses.parse(model=provider.model, store=False, instructions=JUDGE_PROMPT,
                                          input=json.dumps(payload, ensure_ascii=False)[:120000], text_format=Grade)
    return response.output_parsed.model_dump() if response.output_parsed else None


def summarise(results):
    keys = sorted({k for r in results for k in r['scores']})
    return {k: round(mean(r['scores'][k] for r in results if k in r['scores']), 4) for k in keys}


def markdown_report(meta, summary, results, previous):
    lines = [f"# Evaluation report — {meta['timestamp']}", '',
             f"Mode: **{meta['mode']}** · model: `{meta['model']}` · ideas: {len(results)}", '',
             '| Metric | Score | Threshold | Previous |', '| --- | --- | --- | --- |']
    for key, value in summary.items():
        prev = previous.get('summary', {}).get(key) if previous else None
        lines.append(f"| {key} | {value} | {THRESHOLDS.get(key, '')} | {'' if prev is None else prev} |")
    lines += ['', '## Per idea', '', '| Idea | Stages | Doc grounding | Tool calls | Tokens | Seconds | Error |', '| --- | --- | --- | --- | --- | --- | --- |']
    for r in results:
        s = r['scores']
        lines.append(f"| {r['id']} | {s['stages_completed']:.2f} | {s['doc_grounding']:.0f} | {s['tool_calls']} | {s['tokens']} | {s['seconds']} | {r['error'] or ''} |")
    judged = [r for r in results if r.get('judge')]
    if judged:
        lines += ['', '## LLM judge (1-5)', '', '| Idea | Specificity | Feasibility | Grounding | Starter | Reasons |', '| --- | --- | --- | --- | --- | --- |']
        for r in judged:
            j = r['judge']
            lines.append(f"| {r['id']} | {j['specificity']} | {j['feasibility']} | {j['grounding']} | {j['starter_usefulness']} | {j['reasons'][:200]} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mode', choices=['demo', 'live'], default='demo')
    parser.add_argument('--ideas', type=int, default=0, help='Limit the number of ideas (0 = all).')
    parser.add_argument('--only', nargs='*', help='Run only these idea ids.')
    parser.add_argument('--judge', action='store_true', help='Add an LLM-judge rubric (live mode only).')
    parser.add_argument('--no-write', action='store_true', help='Do not write report files.')
    args = parser.parse_args(argv)

    ideas = json.loads((HERE / 'ideas.json').read_text(encoding='utf-8'))
    if args.only:
        ideas = [i for i in ideas if i['id'] in args.only]
    if args.ideas:
        ideas = ideas[:args.ideas]
    key = os.getenv('OPENAI_API_KEY', '') if args.mode == 'live' else ''
    if args.mode == 'live' and not key:
        sys.exit('Live evaluation needs OPENAI_API_KEY.')
    provider = Provider(key, os.getenv('OPENAI_MODEL', 'gpt-5.5'))

    results = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        app = create_app(Path(tmp) / 'eval.db', provider, {'auth_required': False, 'daily_limit': 0})
        with TestClient(app) as client:
            for idea in ideas:
                result = run_idea(client, app.state.db, idea, args.mode)
                if args.judge and args.mode == 'live' and not result['error']:
                    result['judge'] = judge(provider, result)
                print(f"{idea['id']:<18} stages={result['scores']['stages_completed']:.2f} "
                      f"tools={result['scores']['tool_calls']:<3} tokens={result['scores']['tokens']:<7} {result['error'] or 'ok'}")
                results.append(result)
        app.state.db.engine.dispose()

    summary = summarise(results)
    REPORTS.mkdir(exist_ok=True)
    previous_files = sorted(p for p in REPORTS.glob('*.json') if p.stem.endswith(args.mode))
    previous = json.loads(previous_files[-1].read_text(encoding='utf-8')) if previous_files else None
    meta = {'timestamp': datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'), 'mode': args.mode, 'model': provider.model if args.mode == 'live' else None}
    report = markdown_report(meta, summary, results, previous)
    if not args.no_write:
        stem = f"{meta['timestamp']}-{args.mode}"
        slim = [{k: v for k, v in r.items() if k != 'detail'} for r in results]
        (REPORTS / f'{stem}.json').write_text(json.dumps({'meta': meta, 'summary': summary, 'results': slim}, indent=2), encoding='utf-8')
        (REPORTS / f'{stem}.md').write_text(report, encoding='utf-8')
    print('\n' + report)

    failures = [k for k, threshold in THRESHOLDS.items() if summary.get(k, 0) < threshold]
    if failures:
        print('Below threshold: ' + ', '.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
