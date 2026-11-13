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
cd backend
../.venv/Scripts/python.exe -m pytest -q

cd ../frontend
pnpm build
```

See [validation.md](validation.md) for the current verification record.

## Current boundaries

The included deployment is an invite-only Beta. It does not include password reset, email verification, billing, admin screens, distributed job workers, LangGraph, or RAG. Background generation runs inside the API process; an interrupted deploy marks unfinished runs as failed so the user can retry. Generated prototype scripts run inside an opaque-origin iframe with network and external form submission blocked. Exported HTML no longer has that application-level sandbox when opened directly, so review it before use.

The development environment has no configured OpenAI API key, so live model quality, real search relevance, billing, and evaluation across 5–10 real ideas remain unverified.
