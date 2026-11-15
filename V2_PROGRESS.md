# V2 Progress

Design: `docs/V2_ARCHITECTURE.md` · Baseline: `docs/MVP_BASELINE.md`

| # | Phase | Status | Commit |
|---|---|---|---|
| 0 | Scope, docs, CI | done | 620c3ab |
| 1 | Design system & app shell | done | 593469d |
| 2a | Durable runtime (queue, worker, resume) | done | 720b452 |
| 2b | Auth, users, workspaces, tenancy, audit | done | 84dc4f8 |
| 3 | Multi-provider | done | (this commit) |
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

### Phase 2b — Authentication, RBAC, tenancy, audit
- Users, organizations, workspaces, memberships (viewer < editor < admin < owner), API keys, rotating refresh tokens with reuse detection, append-only audit log (migration `0003`; MVP data moved into the Default workspace, first registrant owns it).
- argon2id passwords (uniform-timing login), HS256 access JWTs (15 min), httpOnly SameSite=Strict refresh cookie scoped to `/api/auth`, `eaa_` API keys (hash-only storage, role ≤ creator, bound to a workspace, cannot mint keys).
- Every protected endpoint resolves a `Principal`; every service filters by `workspace_id` (404 cross-tenant) and enforces roles; per-workspace file sandboxes (`WORKSPACE_DIR/<slug>/`); login/registration rate limiting.
- Frontend: in-memory access token + silent refresh + single-flight 401 retry, login/register pages (safe `next` redirects), user/workspace switcher, Organization page (members, API keys shown once, workspaces, audit log; admin sections hidden by role — enforced server-side).
- New deps (justified): `argon2-cffi` (password hashing, OWASP-recommended), `pyjwt` (JWT encode/verify).
- Tests: backend 191 passed / 2 skipped (+18 auth/tenancy/RBAC/API-key/audit tests incl. cross-tenant negatives for every resource and file sandbox isolation); frontend 22 files / 120 passed (+13). ruff, format, mypy, typecheck, lint, build clean.
- Docker: migration 0003 applied to the existing dev DB with data preserved (1 agent, 4 conversations in Default); unauthenticated `/api/agents` → 401; `/api/health` public.

### Phase 3 — Multi-provider
- Adapters: OpenAI, Anthropic, Gemini, OpenAI-compatible (HF router, vLLM, LM Studio, Ollama /v1) and remote Ollama, behind the existing `Provider` protocol; built-in Ollama unchanged (agents keep `provider="ollama"`, `connection_id=null`).
- Workspace provider connections (migration `0004`): Fernet-encrypted API keys (`SECRET_ENCRYPTION_KEY`, rotation via MultiFernet), write-only in the API (hint only), admin-only management, audited, SSRF guard on base URLs, health checks with recorded status, delete blocked while agents use a connection.
- Capabilities are tri-state and never hardcoded: provider-stated values win; otherwise a live tool-calling probe or a user override decides; runs refuse tools on "unknown". Portable params `temperature/top_p/max_tokens`; Ollama-only `num_ctx/think` rejected for other kinds.
- Studio: Providers page (add/test/delete, models with tool-support state, live check, override) and provider selection in the Agent Builder (Ollama-only fields hidden for other providers).
- New deps (justified): `langchain-openai`, `langchain-anthropic`, `langchain-google-genai` (maintained LangChain integrations for the requested providers), `cryptography` (credential encryption). `langchain-core` stays 1.8.0.
- Tests: backend 227 passed / 2 skipped (+36: adapter contract tests with recorded responses for all providers, crypto/rotation, SSRF guard, connection isolation/RBAC/secrets, overrides, probe, unknown-capability refusal); frontend 23 files / 128 passed (+8). ruff, format, mypy, typecheck, lint, build clean.
- Live check (manual): the real OpenAI-compatible adapter against local Ollama `/v1` — discovery (tool support reported as unknown, correctly), streaming with token usage, and a real `ping` tool call (`llama3.2:1b`).
- Not verifiable here: live calls to OpenAI/Anthropic/Gemini (no API keys on this machine) — covered by recorded-response contract tests; manual check with real keys recommended.

## Known issues
- Frontend bundle is 574 kB (minified); route-level code splitting planned with the workflow editor (Phase 8).
- Python text-mode writes on Windows produce CRLF; scripts now write bytes/LF (`.gitattributes` normalizes in git; `*.sh` must be LF for containers).
- `uv` lives at `%APPDATA%\Python\Python314\Scripts\uv.exe` on this machine (not on PATH).

## Blockers
- None.

## Action for the user
- Register your account first on the Docker instance (http://localhost:3000): the first registrant becomes owner of the Default organization holding the pre-V2 data. Set `JWT_SECRET` in `.env`.
