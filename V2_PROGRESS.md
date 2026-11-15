# V2 Progress

Design: `docs/V2_ARCHITECTURE.md` · Baseline: `docs/MVP_BASELINE.md`

| # | Phase | Status | Commit |
|---|---|---|---|
| 0 | Scope, docs, CI | in progress | – |
| 1 | Design system & app shell | pending | – |
| 2 | Durable runtime & tenancy foundation | pending | – |
| 3 | Multi-provider | pending | – |
| 4 | Agent platform (versions, templates) & skills v2 | pending | – |
| 5 | Tools & MCP | pending | – |
| 6 | Human approval | pending | – |
| 7 | Knowledge & memory | pending | – |
| 8 | Visual workflows | pending | – |
| 9 | Multi-agent teams | pending | – |
| 10 | Analytics & observability | pending | – |
| 11 | SDK packaging | pending | – |
| 12 | Production hardening | pending | – |

## Architectural decisions
- Foundation first (durable runs + auth before feature phases).
- Built-in auth: JWT access/refresh + API keys.
- Postgres-only infra: job queue (`SKIP LOCKED`), `LISTEN/NOTIFY`, pgvector, LangGraph Postgres checkpointer for in-flight state only.
- No cloud API keys available: cloud adapters verified with recorded-response contract tests.

## Phase log

### Phase 0 — Scope, docs, CI
- Added `docs/V2_ARCHITECTURE.md`, `docs/MVP_BASELINE.md`, this file.
- Lifted MVP postponements in `PROJECT_SPEC.md` and `CLAUDE.md` (V2 scope now governed by the V2 roadmap).
- Added GitHub Actions CI (backend with Postgres service, frontend).
- Tests: backend 162 passed / 2 skipped; frontend 93 passed; typecheck, lint, build clean.

## Known issues
- `uv` lives at `%APPDATA%\Python\Python314\Scripts\uv.exe` on this machine (not on PATH).

## Blockers
- None.
