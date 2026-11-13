# Validation Record

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

## Agent, RAG and starter-repo update · 2026-11-12

- Backend suite: `40 passed`. New tests cover chunking, ZIP path traversal, per-account document isolation, keyword and hybrid search, the tool loop, step and token limits, rejection of fabricated `doc:` citations, starter path, size and secret checks, and MVP coverage.
- Demo evaluation (`python -m evals.run --mode demo`): 12 ideas completed all 6 stages; every deterministic metric scored 1.0; the 4 ideas with uploads cited retrieved chunks in every stage.
- Alembic `0002` upgraded a fresh SQLite database from `0001`.
- Frontend: `pnpm typecheck` and `pnpm build` passed.
- End-to-end on real servers (uvicorn + `next start`, demo mode): upload through the proxy, all 6 stages with recorded traces, and a ZIP export containing `06-starter/repo/`.
- Not yet verified: the live agent loop against the real OpenAI API, embedding cost, and live output quality (`--judge`).
