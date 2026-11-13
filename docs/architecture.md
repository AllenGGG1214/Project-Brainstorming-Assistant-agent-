# Architecture and Implementation

How Idea Atelier works internally: the implemented workflow, the code map, and current limits. For setup and deployment, see the [main README](../README.md).

## Live generation

Copy `.env.example` to `.env` and configure:

```dotenv
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-5.5
DATABASE_PATH=data/brainstorm.db
```

Restart the backend and create a project in Live mode. The selected model must support the Responses API, Web Search, and Structured Outputs. The API key remains on the backend and is never stored in SQLite or sent to the browser. Live generation consumes API credits and the app does not automatically retry billed requests.

Demo mode uses fixed English artifacts, makes no API calls, and performs no real research. A failed live request never falls back to demo content.

## Deployment notes

Setup, local runs, environment variables, and Render deployment steps are in the [main README](../README.md).

For a custom backend hostname, add it to `TRUSTED_HOSTS`. For multiple values, use a comma-separated list. The browser talks to the Next.js origin and Next.js proxies `/api/*` to FastAPI, so login cookies work as first-party cookies. A Vercel configuration remains available if the frontend is moved there later.

The integration follows the official OpenAI documentation for [Web Search](https://developers.openai.com/api/docs/guides/tools-web-search) and [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Agent and retrieval

### Request flow for one stage

1. `POST /api/projects/{id}/stages/{stage}/generate` checks the stage gates and the daily quota, then starts a background run.
2. `main.generate_job` builds an `AgentContext` (`app/agent/tools.py`). It is scoped to the project, which the user's ownership check already confirmed.
3. `Provider.generate` (`app/provider.py`) runs `run_agent` (`app/agent/harness.py`):
   - **Tools:** the document tools when the project has uploads, plus hosted `web_search` in the research, architecture and starter stages. If no tools apply, the loop is skipped.
   - **Loop:** each step calls the Responses API (`store=False`). The harness runs any function calls and appends the results as `function_call_output` items wrapped in `untrusted_data`. Reasoning items are not replayed.
   - **Limits (`Budget`):** 8 steps, 16 tool calls, 80k tokens and 240 s by default. When a limit is hit, the loop stops and the final call proceeds with the evidence gathered so far.
   - **Trace:** every model step, tool call, tool result, limit summary and final validation is written to `run_steps`.
4. The final `responses.parse` call receives the evidence ledger: web sources, document chunks and findings.
5. Validation: the stage's output format, `validate_traceability`, the web citation check, and `check_doc_refs`.
6. Self-correction: if any of these checks fail, the output and the exact error are sent back to the model, which must return a fixed version. This is tried at most twice (`Provider.max_repairs`); each attempt is a `repair` step in the trace and in `metadata.repairs`. If it is still invalid, the run fails and nothing is saved.

### Retrieval (`app/rag/`)

- `ingest.py`: supported file types, ZIP handling (path traversal, vendored folders and binaries skipped; size and count limits), PDF text extraction, and line-aligned chunks of about 800 tokens with overlap.
- `store.py`: embeddings stored as JSON in `chunks.embedding`. Search combines cosine similarity with BM25-style keyword scoring; it is keyword-only when there are no embeddings. Limits: 20 documents and 2,000 chunks per project. Swap in pgvector here if the corpus needs to grow.
- Live uploads are embedded at upload time and count as one request against the daily quota.

### Evaluation (`backend/evals/`)

```bash
cd backend
python -m evals.run --mode demo             # free; used in CI
python -m evals.run --mode live --ideas 2   # real agent, costs credits
python -m evals.run --mode live --judge     # adds the 1-5 rubric scored by a model
```

Reports are written to `backend/evals/reports/` (git-ignored) and compared with the previous report of the same mode. The command exits with code 1 if a deterministic metric falls below its threshold in `scorers.THRESHOLDS`.

## Implemented workflow

- Create, search, select, resume, and persist projects locally.
- Idea brief → research and decision → function plan → interactive prototype → architecture → starter repo.
- Generate, revise, and explicitly accept every stage.
- GO unlocks downstream design; PIVOT saves a new idea and restarts the brief and research stages; STOP preserves and closes the project.
- Preserve all versions. A successful upstream revision invalidates downstream artifacts without deleting history.
- Run generation in the background, prevent concurrent runs per project, and mark interrupted work as failed after a backend restart.
- Save live Web Search sources, queries, timestamps, raw reports, and citation positions.
- Validate strict structured output, effort ordering, dependency topology, and complete FL-ID traceability.
- Render Markdown, cost summaries, function tables, sandboxed HTML prototypes, Mermaid diagrams, and JSON.
- Export state, all historical versions, Markdown, CSV, source JSON, prototype HTML, and Mermaid in a ZIP file.

## Structure

```text
frontend/                    Next.js App Router + React + TypeScript
  app/page.tsx               Project dashboard and five-stage workspace
  components/ArtifactView    Artifact, source, prototype, and diagram views
backend/app/
  main.py                    FastAPI routes, background runs, gates, and export
  db.py                      SQLite/PostgreSQL transactions, accounts, versions, and run records
  auth.py                    Password hashing and opaque session tokens
  schemas.py                 Input and structured-output validation
  provider.py                Responses API and source handling
  prompts.py                 English generation contract for all stages
  demo.py                    Explicitly labelled English demo artifacts
  agent/harness.py           Bounded tool loop, budgets, and step tracing
  agent/tools.py             Tool registry and per-run AgentContext
  rag/ingest.py              Upload parsing, ZIP safety, and chunking
  rag/store.py               Embeddings and hybrid search
backend/evals/               Evaluation harness: ideas, scorers, report runner
backend/tests/               Workflow, provider, RAG, harness, and starter tests
backend/migrations/          Alembic production database migrations
data/                        Local database and logs; ignored by Git
```

Interactive API docs are available at <http://127.0.0.1:8000/docs>.

## Validation

```bash
cd backend
../.venv/Scripts/python.exe -m pytest -q

cd ../frontend
pnpm build
```

See [validation.md](validation.md) for the current verification record.

## Current boundaries

The included deployment is an invite-only Beta. It does not include password reset, email verification, billing, admin screens, or distributed job workers. Background generation runs inside the API process; an interrupted deploy marks unfinished runs as failed so the user can retry. Generated prototype scripts run inside an opaque-origin iframe with network and external form submission blocked. Exported HTML no longer has that application-level sandbox when opened directly, so review it before use.

The live agent loop, including replaying tool calls through the Responses API with `store=False`, is covered by tests that fake the OpenAI API but has not yet run against the real API. Run `python -m evals.run --mode live --ideas 2` with a key before relying on it.
