# V2 Progress

Design: `docs/V2_ARCHITECTURE.md` · Baseline: `docs/MVP_BASELINE.md`

| # | Phase | Status | Commit |
|---|---|---|---|
| 0 | Scope, docs, CI | done | 620c3ab |
| 1 | Design system & app shell | done | 593469d |
| 2a | Durable runtime (queue, worker, resume) | done | 720b452 |
| 2b | Auth, users, workspaces, tenancy, audit | done | 84dc4f8 |
| 3 | Multi-provider | done | a5641fb |
| 4 | Agent platform (versions, templates) & skills v2 | done | b206514 |
| 5 | Tools & MCP | done | 46e5391 |
| 6 | Human approval | done | 102a708 |
| 7 | Knowledge & memory | done | 1440a68 |
| 8 | Visual workflows | done | (this commit) |
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

### Phase 4 — Agent platform & skills v2
- Draft/published model: the agent row is the draft; `publish` freezes an immutable version (editable + resolved runtime config, skill text included). Chats run the latest published version (unpublished agents keep running their draft — backward compatible); playground conversations always run the draft and stay out of the history. Runs record `agent_version`.
- Version history with field-level diff against the draft and restore-to-draft; duplicate; templates (code-defined, model chosen by the user); portable `eaa.agent/v1` export/import (no ids/secrets; atomic validation; skills reused by slug; connection by name).
- Skills v2: category, tags, search/filter, automatic versioning on content changes with restore, Markdown export/import, built-in skill templates.
- Provider connections pinned by a published version cannot be deleted.
- Studio: status badge, Test (playground sheet), Publish dialog, History sheet (compare/restore), Duplicate, Export in the editor; template picker and JSON import on the agents list; skills page with tags/category, import/export, templates and history.
- Tests: backend 238 passed / 2 skipped (+11 platform tests incl. frozen-skill behaviour, playground vs chat, atomic import, isolation/RBAC); frontend 25 files / 139 passed (+11). ruff, format, mypy, typecheck, lint, build clean.

### Phase 5 — Tools & MCP
- MCP integration on the official `mcp` SDK (v2.3): stdio (admin allow-listed commands, minimal child environment — platform secrets never leak) and Streamable HTTP (SSRF-guarded URLs, encrypted headers). Discovery imports tools **disabled**; admins enable per tool; agents still need explicit grants.
- Custom HTTP tools: GET/POST with typed query/path/body parameters, encrypted headers, host allow-list (`CUSTOM_TOOL_ALLOWED_HOSTS`), link-local/metadata blocking, response caps.
- One `ToolLike` protocol for native and runtime-defined tools; per-run registry (`ToolRegistry.extended`) with only the agent's granted, enabled tools; JSON-Schema argument validation surfaced as `validation` failures; outputs marked as untrusted data.
- Fixed while testing: a grant to a tool disabled after granting crashed the run at bind time — now it is not bound and calls fail with `permission` (regression test added). Discovery gets ≥20 s (stdio start-up); MCP tool errors no longer surface as opaque task-group errors; allow-list accepts a JSON list (paths containing commas).
- Studio: Tools page sections for MCP servers (register, discover, schema inspection, enable switches, health) and custom HTTP tools (parameter builder, write-only headers); source badges.
- New deps (justified): `mcp` (official MCP SDK), `jsonschema` (validating MCP/HTTP tool arguments); dev: `types-jsonschema`.
- Tests: backend 258 passed / 2 skipped (+20: real MCP server over stdio and Streamable HTTP, enable/disable/revocation, validation/error/timeout paths, registration rules, isolation/RBAC, child-env minimality, HTTP tool request building/SSRF/caps); frontend 26 files / 143 passed (+4). ruff, format, mypy, typecheck, lint, build clean.

### Phase 6 — Human approval
- Backend-enforced: calls to tools flagged `requires_approval` per agent, or matching a workspace policy glob, are held by the ToolNode (never executed), emitted as `approval.requested`, and the run ends `waiting_approval` (new terminal event `run.waiting_approval`; mirrored in the TS union).
- Durable without a checkpointer: pending calls are stored as approval requests; when all are decided (approve / approve-with-edited-args / reject / expire), a continuation run (`resume_of`) executes approved calls through the full ToolNode checks, returns rejections to the model, and continues. Waiting runs count as active (one per conversation; migration `0007` updates the partial unique index) and can be cancelled.
- Only authenticated editors decide (the model cannot); decisions are audited; requests expire (`APPROVAL_TTL_S`); policies are admin-managed.
- Studio: approval cards (inspect/edit JSON args, note) in the chat and an Approvals inbox (pending, history, policies) with a live nav badge; per-tool "Require human approval" in the Agent Builder; timeline shows held calls and the paused state.
- Tests: backend 265 passed / 2 skipped (+7: hold/approve/continue, reject with note, edited & invalid args, mixed calls, policies, RBAC/isolation/double-decide, expiry, cancel); frontend 27 files / 149 passed (+6). ruff, format, mypy, typecheck, lint, build clean.

### Phase 7 — Knowledge & memory
- Collections with a per-collection embedding model (built-in Ollama or a provider connection; Anthropic rejected — no embeddings API); uploads (txt/md/csv/json/log/rst/pdf via pypdf) are de-duplicated, extracted at upload and indexed by the run worker (durable job, status polling, re-index).
- Hybrid retrieval: vector similarity + Postgres full-text, fused with RRF; citations (document, page, chunk); output marked untrusted. pgvector is used when installed (CI uses `pgvector/pgvector:pg17`); otherwise an SQL-array fallback — a test checks both rank the same.
- Agent memory: `memory__save`/`memory__search` tools, agent-scoped (other agents cannot read it), list/forget/clear in the UI.
- Decision: the local Docker DB stays `postgres:17-alpine` (switching an existing volume to the Debian-based pgvector image risks collation-dependent index corruption); `POSTGRES_IMAGE` lets new installs choose pgvector.
- Manual check: real embeddings via Ollama `nomic-embed-text` (pulled, 274 MB): 768 dims, normalised, related 0.76 vs unrelated 0.31. Non-embedding models now get an actionable error.
- Studio: Knowledge & memory page (collections, uploads with live status, search tester with citations, per-agent memories); collection picker for `knowledge__search` in the Agent Builder.
- New dep (justified): `pypdf` (PDF text extraction, pure Python).
- Tests: backend 283 passed / 2 skipped (+18: extraction/chunking/RRF, ingestion via the worker, hybrid search, failures, deletion, isolation, agent RAG with citations, private memory, backend parity); frontend 28 files / 153 passed (+4). ruff, format, mypy, typecheck, lint, build clean.

### Phase 8 — Visual workflows
- Backend-defined `WorkflowSpec` with 11 node types; strict server validation (structure, DAG, handles, configs, template/expression references, workspace references); the canvas JSON is never trusted.
- Engine compiles specs to a LangGraph `StateGraph` (parallel fan-out + deferred joins, conditional edges, approval pause/resume, timeout, cancel), DB-free via an injected `WorkflowServices`; agent/LLM/tool/knowledge/memory nodes reuse the existing checks (`build_agent_run`, provider resolver, `ToolNode.run_single`).
- Safe condition language (whitelisted AST; sandbox negative tests) and `{{ }}` templates.
- Durable: workflow runs are `runs` rows (`kind="workflow"`) — same queue/worker/heartbeat/cancel/stream/resume; approval steps use the approval system and resume without re-running earlier nodes.
- Studio: workflows list (blank/templates/import), React Flow editor (drag-and-drop palette + click-to-add, typed handles per branch, connection rules, inspector forms, undo/redo, copy/paste/duplicate/delete, auto-layout via dagre, minimap, server problems on nodes, export, publish, versions/restore) and a run panel with live node status, path highlighting, log and output. The editor is lazy-loaded (258 kB chunk).
- Limitations (documented): no loops; an approval node inside a parallel branch resumes only its own branch; agent nodes cannot pause for tool approval (use an Approval node).
- New deps (justified): `@xyflow/react` (maintained React Flow), `@dagrejs/dagre` (auto-layout).
- Tests: backend 323 passed / 2 skipped (+40: spec validation matrix, expression sandbox, engine behaviours, API end-to-end through the worker incl. agent/tool nodes, approval continuation, RBAC/isolation, templates); frontend 30 files / 162 passed (+9: graph helpers, editor interactions, template creation, live run). ruff, format, mypy, typecheck, lint, build clean.

## Known issues
- Main frontend bundle is ~678 kB minified (203 kB gzip); the workflow editor is split out; further route splitting is a Phase 12 task.
- Python text-mode writes on Windows produce CRLF; scripts now write bytes/LF (`.gitattributes` normalizes in git; `*.sh` must be LF for containers).
- `uv` lives at `%APPDATA%\Python\Python314\Scripts\uv.exe` on this machine (not on PATH).

## Blockers
- None.

## Action for the user
- Register your account first on the Docker instance (http://localhost:3000): the first registrant becomes owner of the Default organization holding the pre-V2 data. Set `JWT_SECRET` in `.env`.
