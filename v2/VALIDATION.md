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

## V3 basic verification · 2026-09-12

- Full backend suite: **40 passed** with `TEST_DATABASE_URL` pointing to an isolated local PostgreSQL 18 cluster. The V3 durability cases run on both SQLite and PostgreSQL; original provider contract, authentication, and workflow tests also pass.
- Recovery coverage includes queued generation after restart, saved approval after restart, result saved before checkpoint, artifact committed before a simulated process crash, unknown model-call handling, expired-worker fencing, stale upstream versions, every stage's interrupt, GO/PIVOT/STOP routes, legacy-project continuation, and approval synchronization retry.
- Existing account-isolation tests include unauthorized access to the new recovery endpoint.
- PostgreSQL Alembic migration tested from a fresh database through `0001`, then `0002`; `alembic current` reports `0002 (head)`.
- Frontend `pnpm typecheck` and `pnpm build` pass after the final interface changes.
- Updated dependency lock: `pip check` reports no broken requirements.
- No live model requests were made. Real search quality, API costs, deployed-service restart behavior, browser interaction for the new banners, and 5–10 real Ideas remain unverified. Code has not been pushed or deployed by this change.
- Without `TEST_DATABASE_URL`, PostgreSQL durability tests are explicitly skipped rather than represented as validated.

## V3 browser acceptance · 2026-09-13

- Verified the production frontend in the local browser against an isolated acceptance SQLite database: project creation, all five stages, persistent approval after refresh, explicit GO, completion, Mermaid rendering, and a ZIP download event.
- Verified the sandboxed prototype adds a record and shows an unmatched-filter empty state.
- Verified an upstream revision reopens downstream stages while preserving accepted history; fixed project-list progress refresh after background generation finishes.
- Verified PIVOT saves the revised idea and resets stage progress; STOP preserves artifacts and removes generation controls.
- Added `backend/backup_database.py` to create a credential-safe pg_dump custom archive and verify its catalog before deployment. Render Free Tier exposes no backup export action.
- Production backup, live API acceptance, pushing/merging the release, and public deployment remain pending configuration of `OPENAI_API_KEY` and the external PostgreSQL `DATABASE_URL` in local `v2/.env`.
