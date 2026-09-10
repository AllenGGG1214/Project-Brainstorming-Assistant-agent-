# V2 Validation Record

Date: 2026-09-10. Environment: Windows, Python 3.12, Node.js 24. Dependency versions are recorded in the lock files.

## Completed checks

- Backend test suite covers the five stages, human decision gate, PIVOT, STOP, version invalidation, retry behavior, concurrency protection, restart recovery, ZIP export, estimate validation, missing-key handling, and tool-source extraction.
- OpenAI SDK request contracts are tested with `httpx.MockTransport`: mandatory Web Search for research, source transfer, strict JSON Schema, `store=False`, refusals, and missing-source failures.
- The frontend production build performs compilation, TypeScript checking, and static page generation.
- The V1 state-machine smoke test still passes.
- Browser verification covers project creation, all five stages, GO, artifact acceptance, Mermaid rendering, prototype interaction, persistence after refresh, and ZIP download.
- The generated demo prototype successfully adds a record and displays its no-results filter state.
- A 390 × 844 viewport check found no horizontal page overflow.

## Not yet verified

- Live API generation and live Web Search because `OPENAI_API_KEY` is not configured in the development environment.
- Quality and source relevance across 5–10 real ideas.
- Public deployment, multi-user behavior, penetration testing, or load testing.

Two Starlette dependency deprecation warnings may appear in tests; they do not affect the passing results.
## Production-readiness update · 2026-09-10

- Backend suite: `16 passed` (workflow, persistence, failure recovery, invite auth, sessions, and account isolation).
- Frontend: `pnpm build` completed with TypeScript and static page generation.
- Database migration: Alembic `0001` upgraded a fresh SQLite database successfully; the same migration targets Render PostgreSQL through `DATABASE_URL`.
- Dependency check: `pip check` reported no broken requirements.
