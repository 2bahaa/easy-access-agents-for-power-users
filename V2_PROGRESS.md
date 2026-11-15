# V2 Progress

Design: `docs/V2_ARCHITECTURE.md` · Baseline: `docs/MVP_BASELINE.md`

| # | Phase | Status | Commit |
|---|---|---|---|
| 0 | Scope, docs, CI | done | 620c3ab |
| 1 | Design system & app shell | done | 593469d |
| 2a | Durable runtime (queue, worker, resume) | done | (this commit) |
| 2b | Auth, users, workspaces, tenancy, audit | pending | – |
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

### Phase 1 — Design system & app shell
- Tokens: status colors (`success/warning/danger/info`), class-based dark mode, persisted theme preference (system/light/dark) with no-flash boot script.
- Shell: collapsible grouped sidebar (rail + tooltips, Ctrl+B, persisted), ⌘K/Ctrl+K command palette (actions, navigation, agents, recent conversations, theme), theme menu, health rail indicator.
- Overview dashboard (`/overview`, new default route) from live API data only; explicit "unavailable" states.
- New deps (justified): `cmdk` (accessible command palette), `@radix-ui/react-dialog` (cmdk peer), `@radix-ui/react-tooltip`, `@radix-ui/react-dropdown-menu` (accessible focus-managed overlays instead of hand-rolled ones).
- Tests: frontend 19 files / 106 passed (+13: theme, shell, palette, overview); typecheck, lint, build clean. Backend unchanged.

### Phase 2a — Durable runtime
- Runs are queued in Postgres (`status=queued`) and executed by `RunWorker` (embedded in the API by default; `python -m app.worker` standalone; Docker runs a separate `worker` service).
- Claiming with `FOR UPDATE SKIP LOCKED`; NOTIFY wake-ups + poll fallback; worker heartbeats; reaping of runs whose worker died (terminal `run.failed` event so followers end).
- Events fan out via `LISTEN/NOTIFY` in the same transaction as their rows; batched writes (one tx per burst); oversized persisted events sent by reference; token deltas split at the source (≤1,500 chars).
- `GET /runs/{id}/stream` with `Last-Event-ID`/`?after=` resume; client disconnect no longer cancels (documented API change); cancel via DB flag works across processes; queued runs cancel immediately.
- One active run per conversation enforced by a partial unique index (migration `0002`).
- Frontend: chat reattaches to an active run after reload; leaving the page only stops following.
- Test fixtures now use committed data + TRUNCATE and the real lifespan/worker (no mocked transport of runs).
- Tests: backend 173 passed / 2 skipped (+11: durability suite incl. two-worker exclusivity, reaping, resume, large events, API-without-worker); frontend 107 passed (+1 reattach). ruff, format, mypy, typecheck, lint, build clean.
- Manual E2E (Docker, llama3.2:1b): client disconnect → run keeps `running` → `docker compose restart backend` → new API instance follows the run live → `completed`, answer persisted.

## Known issues
- Frontend bundle is 574 kB (minified); route-level code splitting planned with the workflow editor (Phase 8).
- Python text-mode writes on Windows produce CRLF; scripts now write bytes/LF (`.gitattributes` normalizes in git; `*.sh` must be LF for containers).
- `uv` lives at `%APPDATA%\Python\Python314\Scripts\uv.exe` on this machine (not on PATH).

## Blockers
- None.
