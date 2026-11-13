# Validation

Current state of what has and has not been verified. Last updated 2026-11-13.

## Verified

| Area | How | Result |
|---|---|---|
| Backend | `python -m pytest` in `backend/` | 41 passed: auth and account isolation, all six stages and approval gates, PIVOT / STOP, versioning, recovery after restart, ZIP export, chunking and ZIP path traversal, keyword and hybrid search, the agent tool loop and its limits, rejection of fabricated `doc:` citations, self-correction, and starter-repo path, size, secret and MVP-coverage checks |
| OpenAI request format | Tests with `httpx.MockTransport` | Web search required for research, `store=False`, strict JSON schema, refusals and missing sources handled |
| Demo evaluation | `python -m evals.run --mode demo` | 12 ideas completed all 6 stages; every deterministic metric scored 1.0; ideas with uploads cited retrieved chunks in every stage |
| Database | Alembic on a fresh SQLite database | `0001` → `0002` upgrade succeeds; the same migrations run on Render PostgreSQL |
| Frontend | `pnpm typecheck`, `pnpm build` | Pass |
| End to end | uvicorn + `next start`, demo mode | Upload through the proxy, all 6 stages with recorded traces, ZIP export containing `06-starter/repo/` |
| Mobile layout | 390 × 844 viewport | No horizontal overflow |

## Not yet verified

- The live agent loop against the real OpenAI API, including self-correction. Run `python -m evals.run --mode live --ideas 2` with a key.
- Embedding cost, cost per project, and live output quality (`--judge`).
- Load testing and penetration testing.
