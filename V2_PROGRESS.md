# V2 Progress

Design: `docs/V2_ARCHITECTURE.md` · Baseline: `docs/MVP_BASELINE.md`

| # | Phase | Status | Commit |
|---|---|---|---|
| 0 | Scope, docs, CI | done | 620c3ab |
| 1 | Design system & app shell | done | (this commit) |
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

### Phase 1 — Design system & app shell
- Tokens: status colors (`success/warning/danger/info`), class-based dark mode, persisted theme preference (system/light/dark) with no-flash boot script.
- Shell: collapsible grouped sidebar (rail + tooltips, Ctrl+B, persisted), ⌘K/Ctrl+K command palette (actions, navigation, agents, recent conversations, theme), theme menu, health rail indicator.
- Overview dashboard (`/overview`, new default route) from live API data only; explicit "unavailable" states.
- New deps (justified): `cmdk` (accessible command palette), `@radix-ui/react-dialog` (cmdk peer), `@radix-ui/react-tooltip`, `@radix-ui/react-dropdown-menu` (accessible focus-managed overlays instead of hand-rolled ones).
- Tests: frontend 19 files / 106 passed (+13: theme, shell, palette, overview); typecheck, lint, build clean. Backend unchanged.

## Known issues
- Frontend bundle is 574 kB (minified); route-level code splitting planned with the workflow editor (Phase 8).
- `uv` lives at `%APPDATA%\Python\Python314\Scripts\uv.exe` on this machine (not on PATH).

## Blockers
- None.
