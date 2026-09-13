# V2 · Idea Atelier

## V3 basic upgrade

This directory now also contains the V3 basic implementation. `WORKFLOW_ENGINE=langgraph` (the default) runs stage generation through a persistent LangGraph workflow; `WORKFLOW_ENGINE=v2` selects the legacy generator for new runs. Existing V3 jobs still recover when the flag is changed. See [the release and deployment guide](../docs/V3_BASIC_RELEASE.md) for scope, recovery behavior, and rollout requirements.

The basic release includes five named generation nodes, saved results, approval interrupts, GO/PIVOT/STOP outcomes, database leases, and restart recovery. The recovery scheduler runs inside the API process for this low-traffic beta. Next-stage generation remains user initiated. Parallel research, a separate worker, cancellation, and run-level spending budgets belong to the full V3 MVP.

A deployable project planning app with an English interface, a five-stage approval workflow, private accounts, and SQLite or PostgreSQL persistence.

## Quick start on Windows

Requirements: Python 3.11+, Node.js 20.9+, and pnpm. The scripts also recognize the runtimes bundled with Codex.

```powershell
cd v2
./setup.ps1
./start.ps1
```

Open <http://127.0.0.1:3000>. Initial setup needs access to Python and npm package registries. Logs are written to `v2/data/`.

## Manual start on macOS or Linux

Create a virtual environment in `v2`, activate it, and install the locked backend dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.lock.txt
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
cd v2/frontend
pnpm install --frozen-lockfile
pnpm dev
```

## Live generation

Copy `v2/.env.example` to `v2/.env` and configure:

```dotenv
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-5.5
DATABASE_PATH=data/brainstorm.db
```

Restart the backend and create a project in Live mode. The selected model must support the Responses API, Web Search, and Structured Outputs. The API key remains on the backend and is never stored in SQLite or sent to the browser. Live generation consumes API credits and the app does not automatically retry billed requests.

Demo mode uses fixed English artifacts, makes no API calls, and performs no real research. A failed live request never falls back to demo content.

## Deploy entirely on Render

The repository includes a Render Blueprint for the Next.js frontend, FastAPI service, and PostgreSQL database. This is the simplest deployment for a low-traffic Beta.

1. Push this repository to GitHub.
2. In Render, create a Blueprint from the repository's `render.yaml`.
3. Set `OPENAI_API_KEY` and a long random `INVITE_CODE`. Render supplies `DATABASE_URL`, configures the frontend origin, and runs `alembic upgrade head` when the API starts.
4. Let the Blueprint create `idea-atelier-web`, `idea-atelier-api`, and `idea-atelier-db`.
5. Open the `idea-atelier-web` URL, choose **Have an invite?**, and create the first account with your invite code.

Production defaults require authentication, use secure HttpOnly session cookies, isolate projects by account, and limit each account to 20 live generation requests per UTC day. Change `DAILY_GENERATION_LIMIT` in Render if needed. Keep `API_ORIGIN` and every secret in platform environment variables; do not commit them.

For a custom backend hostname, add it to `TRUSTED_HOSTS`. For multiple values, use a comma-separated list. The browser talks to the Next.js origin and Next.js proxies `/api/*` to FastAPI, so login cookies work as first-party cookies. A Vercel configuration remains available if the frontend is moved there later.

The integration follows the official OpenAI documentation for [Web Search](https://developers.openai.com/api/docs/guides/tools-web-search) and [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Implemented workflow

- Create, search, select, resume, and persist projects locally.
- Idea brief → research and decision → function plan → interactive prototype → architecture.
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
backend/tests/               Workflow and provider contract tests
backend/migrations/          Alembic production database migrations
data/                        Local database and logs; ignored by Git
```

Interactive API docs are available at <http://127.0.0.1:8000/docs>.

## Validation

```bash
cd v2/backend
../.venv/Scripts/python.exe -m pytest -q

cd ../frontend
pnpm build
```

See [VALIDATION.md](VALIDATION.md) for the current verification record.

## Current boundaries

The included deployment is an invite-only Beta. It does not include password reset, email verification, billing, admin screens, distributed job workers, or RAG. V3 basic generation runs inside the API process with durable checkpoints and leased recovery; tasks do not execute while the service sleeps. Interrupted calls with unknown results require manual retry and may already have consumed API credits. Legacy V2 unfinished runs retain their previous failed-on-restart behavior. Generated prototype scripts run inside an opaque-origin iframe with network and external form submission blocked. Exported HTML no longer has that application-level sandbox when opened directly, so review it before use.

The development environment has no configured OpenAI API key, so live model quality, real search relevance, billing, and evaluation across 5–10 real ideas remain unverified.
