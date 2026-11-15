# Architecture

See `PROJECT_SPEC.md` for requirements and `API_DESIGN.md` for the HTTP/SSE contract.

## 1. Overview

```
React (Vite)  ── REST (JSON) ──►  FastAPI  api/  (routers, schemas, SSE)
   │  Studio, Chat, Timeline         │
   └── SSE (fetch stream) ◄──────────┤
                                     ▼
                              services/  (agents, skills, conversations, runs)
                                     │
               ┌─────────────────────┼─────────────────────┐
               ▼                     ▼                     ▼
          runtime/               tools/ + skills/        db/ (SQLAlchemy, Alembic)
   LangGraph graph, limits,   registry, schemas,           │
   events, providers/         calculator, file_reader      ▼
               │                                       PostgreSQL
               ▼
         Ollama (host :11434)
```

**Dependency rule:** `api` → `services` → (`runtime`, `db`). `runtime` depends on `tools`, `skills` and `providers` but never on `db` or FastAPI.

## 2. Technology decisions

| Concern | Choice | Rationale |
|---|---|---|
| API | FastAPI, Pydantic v2, `pydantic-settings` | Typed validation, OpenAPI, async |
| Orchestration | LangGraph 1.x custom `StateGraph` (`agent` ⇄ `tools`) | Our own tool node enforces permissions, validation, limits, timeouts and emits events; LangGraph enables subgraphs/HITL later |
| LLM | `langchain-ollama` `ChatOllama` via a provider registry | Thin seam: new provider = one factory |
| Persistence | PostgreSQL 17, SQLAlchemy 2 async + asyncpg, Alembic | Our tables are the only history; no LangGraph checkpointer in MVP |
| Streaming | SSE: `StreamingResponse` + FastAPI's built-in SSE frame formatter (`fastapi.sse`), own 15 s keep-alive; frontend `fetch` + small SSE parser | One POST per turn streams its run; no extra dependency or job queue |
| Frontend | React, TypeScript, Vite, Tailwind CSS v4, React Router, TanStack Query | Standard and minimal |
| Tooling | uv, ruff, mypy, pytest, pytest-asyncio, httpx; Vitest, React Testing Library | |
| Containers | Docker Compose: `db`, `backend` (uv-built venv on `python:3.12-slim`, non-root, migrations on start, 1 worker), `frontend` (Vite build served by nginx, `/api` proxied with SSE buffering off); Ollama on host via `host.docker.internal` | GPU passthrough on Windows is impractical |

Verified versions (Phase 0): Python 3.12, LangGraph 1.2.22, langchain-core 1.8, langchain-ollama 1.1.0, Ollama 0.40.

## 3. Component responsibilities

### Backend (`backend/app/`)
| Module | Responsibility |
|---|---|
| `main.py` | App factory, lifespan (DB engine, registries, skill seeding), CORS, router mounting |
| `config.py` | `Settings` from environment: DB URL, Ollama URL, `WORKSPACE_DIR`, global caps, run worker, auth (`JWT_SECRET`, token TTLs, registration, cookie, rate limits) |
| `security.py` | Pure credential primitives: argon2id password hashing (+ dummy hash for uniform login timing), HS256 access JWTs, opaque refresh tokens, API key generation/parsing/hash comparison |
| `services/auth_service.py`, `principal.py` | Register/login/refresh rotation/logout; `resolve_principal` (JWT or API key → `Principal(user, org, workspace, role)`); every service call receives the principal and filters by `workspace_id` |
| `services/tenancy_service.py`, `audit_service.py` | Workspaces, members (role rules: no granting above own role, keep ≥1 owner), API keys; audit trail |
| `api/deps.py` → `PrincipalDep` | Resolves the principal from `Authorization` + `X-Workspace-Id` for every protected router; `api/ratelimit.py` throttles login/registration (per process) |
| `api/routers/` | HTTP endpoints only: parse/validate, call a service, map results/errors |
| `api/sse.py` | Serialize `AgentEvent`s to SSE frames, keep-alives; `follow_run_sse` streams a run from the database (disconnect only stops following) |
| `api/errors.py` | Domain exceptions → problem-JSON responses |
| `schemas/` | Pydantic request/response models |
| `services/` | Use cases: agent/skill CRUD with validation, conversation management, run orchestration (`run_service`: build `AgentConfig` snapshot, queue the run with the user message, rebuild it for a worker, apply results) |
| `services/run_queue.py` | Durable run queue on Postgres: claim (`FOR UPDATE SKIP LOCKED`), heartbeat, cancel (queued → cancelled at once; running → `cancel_requested` + NOTIFY), reaping of runs whose worker died, batched event writes |
| `services/pubsub.py`, `run_stream.py` | `LISTEN/NOTIFY` helpers; `follow_run` = replay persisted events, then live notifications (dedup by `seq`) |
| `worker/` | `RunWorker`: claims queued runs, executes `AgentRun`s, writes events in batches, heartbeats, honours cancel flags. Embedded in the API (`RUN_WORKER_EMBEDDED=true`) or standalone (`python -m app.worker`) |
| `db/` | SQLAlchemy models and async engine/session factory. Services query via the session directly; a repository layer is added only if query logic starts to repeat |
| `runtime/providers/` | `Provider` protocol (list models, capabilities, build chat model, classify provider errors), registry + `build_provider(spec)`, Ollama, and `cloud.py` adapters: OpenAI / OpenAI-compatible (ChatOpenAI), Anthropic (ChatAnthropic), Gemini (ChatGoogleGenerativeAI). Discovery uses each provider's REST listing over httpx; capabilities are tri-state (`None` = not stated, never guessed) |
| `tools/external.py`, `tools/mcp_client.py` | Runtime-defined tools (`McpTool`, `HttpTool`) satisfying the `ToolLike` protocol: JSON-Schema argument validation, capped/untrusted-marked output, outbound host allow-list + SSRF guard; MCP client on the official `mcp` SDK (v2): stdio (minimal child env) and Streamable HTTP, one session per operation, bounded by timeouts |
| `services/capability_service.py` | MCP server registry (admin, audited, encrypted env/headers), discovery (tools imported disabled), enable/disable, custom HTTP tools, grant validation and per-run construction of an agent's external tools (`ToolRegistry.extended`) |
| `services/approval_service.py` | Approval policies (globs), request creation when a run pauses, decisions (editor+, audited), expiry (worker maintenance), continuation-run creation; `ToolNode` holds calls whose grant `requires_approval`; `AgentRun` answers them on resume (`ResumeDecisions`) before continuing the graph |
| `crypto.py` | `SecretBox`: Fernet/MultiFernet encryption of stored credentials (key rotation) |
| `services/provider_service.py` | Connections CRUD (admin, audited, SSRF-guarded base URLs), `ProviderResolver` (workspace-scoped connection → provider with decrypted key in memory + capability overrides), health checks, model listing, tool-support overrides and the live probe |
| `runtime/graph.py`, `state.py` | LangGraph `StateGraph` definition and state |
| `runtime/tool_node.py` | Authorize → limit-check → validate → execute with timeout → emit events |
| `runtime/events.py` | `AgentEvent` discriminated union |
| `runtime/limits.py` | Effective limits = min(agent setting, global cap) |
| `runtime/executor.py` | `AgentRun(request, provider, tools, caps, ctx)`: `stream()` yields `AgentEvent`s, `cancel()`, then `result` (status, tool_call_count, usage, new messages) |
| `tools/` | `Tool` base, registry, `calculator`, `file_reader` |
| `skills/` | Markdown/frontmatter loader, system-prompt composition |

### Frontend (`frontend/src/`)
| Folder | Responsibility |
|---|---|
| `api/` | `client.ts` (fetch wrapper, problem-JSON → `ApiError`, `streamMessage()` async generator), `types.ts` (mirrors backend schemas), `events.ts` (TS union mirroring `AgentEvent`), `sse.ts` (incremental SSE parser), `queries.ts` (TanStack Query hooks + cache invalidation) |
| `features/` | Route-level containers that fetch data and wire mutations: `agents/`, `skills/`, `tools/`, `chat/` (`ChatPage`, `ConversationList`, `useRunStream`) |
| `components/` | Prop-driven SDK candidates (no fetching): `AgentBuilder`, `ModelPicker`, `SkillSelector`, `ToolPicker`, `SchemaFields`, `SkillEditor`, `AgentChat`, `AgentRunTimeline`, `Markdown` (safe renderer — React elements only, no HTML injection) |
| `components/ui/` | Design-system primitives: Button/LinkButton, Field/Input/Select/Textarea, Card/Section, Badge, Switch, ConfirmDialog, Toast, Tooltip (Radix), empty/error/skeleton states |
| `lib/` | Pure logic: agent/skill form mapping and validation, `modelDefaults` (settings adjusted when a model is picked: thinking, run timeout, tools), `runReducer` (events → run state/timeline, also replays persisted `run_events`), `transcript` (messages + runs → chat items), schema helpers, formatting |
| `layout/`, `routes.tsx` | App shell: collapsible grouped sidebar (`nav.ts` is the single nav source; Ctrl+B), ⌘K command palette (`CommandMenu`, cmdk), theme menu, live system status; page header; routes (`/` → `/overview`) |
| `features/overview/` | Overview dashboard built only from live API data; unavailable metrics render as “—” with an explanation |

**Styling:** Tailwind v4 with semantic color tokens (`canvas`, `surface`, `line`, `fg`, `muted`, status `success`/`warning`/`danger`/`info`) defined in `src/index.css`. The theme is class-driven (`html.dark`, `@custom-variant dark`): `lib/theme.ts` stores the preference (system/light/dark) in localStorage and an inline script in `index.html` applies it before first paint; "system" follows `prefers-color-scheme` live. **Tool config forms** are generated from each tool's Pydantic `config_schema` (title, description, default, examples), so new tools need no UI code. **Dev proxy:** Vite forwards `/api` to `127.0.0.1:8000` (one origin, no CORS in development); it streams SSE without buffering.

**Chat data flow:** `useRunStream` POSTs the message and reduces streamed events with `runReducer`; the page shows persisted transcript + the live run. When the run ends, the conversation is refetched and the live view is swapped for the persisted messages (same message ids, so no duplicates). Timelines of past runs are rebuilt from `GET /runs/{id}/events` with the same reducer. The chat route is `agents/:agentId/chat/:conversationId?` (one route, optional segment) so creating a conversation mid-send does not remount the page. Closing the page aborts the request, which the backend treats as cancel.

## 4. Folder structure

```
easy-access-agents/
├─ backend/
│  ├─ pyproject.toml  uv.lock  alembic.ini
│  ├─ alembic/versions/
│  ├─ skills/                 # built-in skill .md files (seed)
│  ├─ scripts/                # dev scripts (e.g. Ollama spike)
│  ├─ app/
│  │  ├─ main.py  config.py
│  │  ├─ api/  deps.py  errors.py  sse.py  routers/
│  │  ├─ schemas/  services/
│  │  ├─ db/  session.py  models.py
│  │  ├─ runtime/  graph.py  state.py  events.py  limits.py  executor.py  tool_node.py  providers/
│  │  ├─ tools/  base.py  registry.py  calculator.py  file_reader.py
│  │  └─ skills/  loader.py  prompt.py
│  └─ tests/  unit/  integration/  conftest.py
├─ frontend/
│  └─ src/  api/  features/  components/  pages/  test/
├─ workspace/                 # file_reader sandbox
├─ docs/
├─ docker-compose.yml  .env.example  README.md  CLAUDE.md
```

## 5. Database schema

**Agent versions & skills v2 (V2, migration `0005`):** `agent_versions(agent_id, version, write_config, runtime_config, note, created_by)` — the `agents` row is the draft; a published version is immutable and carries the resolved runtime config (skill text frozen). `conversations.kind` (`chat` | `playground`), `runs.agent_version`. `skills` gain `category`, `tags text[]`, `version`; `skill_versions` keeps earlier states.

**Tenancy (V2, migration `0003`):** `organizations` → `workspaces` (globally unique immutable `slug`, also the workspace's file-sandbox folder `WORKSPACE_DIR/<slug>/`); `users` (lower-cased unique email, argon2id `password_hash`); `memberships(org_id, user_id, role)`; `api_keys` (SHA-256 hash + lookup prefix, role ≤ creator's, optional expiry, revocation); `refresh_tokens` (hash, `family_id` for reuse detection); `audit_log` (append-only, written in the same transaction as the action). `agents`, `skills`, `conversations` and `runs` carry `workspace_id` (FK, cascade); skill slugs are unique per workspace. Pre-existing data was moved into the Default organization/workspace (`slug = default`).

| Table | Columns | Notes |
|---|---|---|
| `agents` | `id uuid pk`, `name`, `description`, `provider`, `model`, `model_params jsonb`, `system_prompt text`, `max_tool_calls int` (default 8), `run_timeout_s int` (default 120), `created_at`, `updated_at` | `model_params`: temperature, num_ctx, think |
| `skills` | `id uuid pk`, `slug unique`, `name`, `description`, `content_md text`, `is_builtin bool`, `created_at`, `updated_at` | |
| `agent_skills` | `agent_id fk`, `skill_id fk`, `position int` | pk(agent_id, skill_id) |
| `agent_tools` | `agent_id fk`, `tool_name text`, `config jsonb` | pk(agent_id, tool_name); name validated against registry, config by the tool's config model |
| `conversations` | `id uuid pk`, `agent_id fk`, `title`, `created_at`, `updated_at` | |
| `messages` | `id uuid pk`, `conversation_id fk`, `run_id fk null`, `seq int`, `role` (`user`/`assistant`/`tool`), `content text`, `tool_calls jsonb null`, `tool_call_id null`, `tool_name null`, `created_at` | unique(conversation_id, seq) |
| `runs` | `id uuid pk`, `conversation_id fk`, `agent_id fk`, `status`, `agent_snapshot jsonb`, `tool_call_count int`, `usage jsonb`, `error text null`, `started_at`, `finished_at` | status: `running`, `completed`, `failed`, `cancelled`, `limit_exceeded`, `timeout` |
| `run_events` | `id bigserial pk`, `run_id fk`, `seq int`, `type`, `payload jsonb`, `created_at` | All events except token/reasoning deltas |

Tools are not stored as rows; the catalog comes from the code registry. Deleting an agent cascades to its `agent_skills`, `agent_tools`, conversations and runs.

## 6. Tools and skills

**Tool contract** (`app/tools/base.py`): `name`, `description`, `Args` (Pydantic model → JSON schema), `Config` (Pydantic model for per-agent config), `timeout_s`, `async run(args, config, ctx) -> str`. The registry exposes the catalog and builds the provider-format schema list for an agent's permitted tools only.

**file_reader sandbox:** root = `WORKSPACE_DIR`; optional per-agent `subdir` must resolve inside the root. Path resolution uses `Path.resolve()` and a containment check after resolving symlinks. Rejects absolute paths outside root, traversal, non-files, files over the size limit, and non-UTF-8 content.

**Skills:** stored in DB, seeded from `backend/skills/*.md` (YAML frontmatter: `name`, `slug`, `description`). System prompt = agent prompt + `## Skills` section with each attached skill in `position` order. A later upgrade can expose skills via an on-demand `load_skill` tool without schema changes.

## 7. Agent execution lifecycle

1. `POST /api/conversations/{id}/messages` with the user's content.
2. `run_service` loads agent, skills and tool configs → immutable `AgentConfig`; creates a **queued** `runs` row with `agent_snapshot` and persists the user message in one transaction, then NOTIFYs workers. A partial unique index guarantees one active (queued/running) run per conversation across all processes (409).
3. A run worker claims the run (`SKIP LOCKED`), rebuilds the `AgentRun` from the snapshot and the stored history, and executes it. The API response follows the run's events from the database (step 9).
4. **Pre-flight:** provider resolves the model; if the agent has tools and the model lacks the `tools` capability → `run.failed` (`model_no_tool_support`).
5. Compose system prompt (agent prompt + skills). Bind only permitted tool schemas.
6. **Graph loop** (`graph.astream(..., stream_mode=["messages", "custom"], version="v2")`):
   - `agent` node calls the LLM; token chunks with `langgraph_node == "agent"` → `message.delta` (thinking → `reasoning.delta`).
   - If tool calls → `tools` node, per call (events go through the LangGraph stream writer):
     a. `tool_call_count < max_tool_calls`? else end the run: status `limit_exceeded`, `run.failed`
     b. emit `tool.call.started`
     c. tool permitted for this agent? else `tool.call.failed` (`permission`)
     d. validate args with `Args` (after unwrapping a schema-echo wrapper some small models emit, e.g. `{"type":"function","parameters":{...}}`) → on error `tool.call.failed` (`validation`)
     e. `asyncio.wait_for(tool.run(...), timeout_s)` → `tool.call.completed`, or `tool.call.failed` (`timeout`/`execution`)
     f. append a `ToolMessage` with the result or a user-safe error, so the model can recover
   - Loop until the model replies without tool calls; LangGraph `recursion_limit` is derived from `max_tool_calls` as a backstop.
7. The whole run is wrapped in `asyncio.timeout(run_timeout_s)` → status `timeout`.
8. The worker writes events in batches (one transaction per burst: `run_events` rows for persisted events + NOTIFY for every event, in order). The terminal event is committed together with the assistant/tool messages and final status/usage, so a follower never sees the end before the messages.
9. Followers (`POST …/messages` response, `GET /runs/{id}/stream`) LISTEN on the run's channel, replay persisted events after `Last-Event-ID`, then stream live events until the terminal event. A client disconnect only stops following; `POST /runs/{id}/cancel` stops the run (`cancelled`).
10. Workers heartbeat their runs; a run whose worker stops heartbeating for `RUN_STALE_AFTER_S` is marked `failed` ("Interrupted by a server restart") with a terminal event.

## 8. Streaming design

The graph runs in a producer task that feeds a queue; `AgentRun.stream()` reads the queue. The run timeout and cancellation therefore apply only to agent work, never to the consumer's code. Token text is emitted in pieces of at most 1,500 characters so every delta fits a NOTIFY payload. Graph streaming uses `stream_mode=["messages", "custom", "updates"]` (`version="v2"`): `messages` → token deltas, `custom` → tool events from the tool node's stream writer, `updates` → completed messages, usage and tool-call counts.

When `max_tool_calls` is reached, pending tool calls still receive an error `ToolMessage` so stored history remains well-formed, then the run ends with `limit_exceeded`.

The runtime yields `AgentEvent` objects (Pydantic discriminated union in `runtime/events.py`). The worker persists every non-delta event to `run_events`, publishes every event on the run's NOTIFY channel (events over the 8 kB NOTIFY limit are sent as a reference to their committed row), and on completion stores the new messages and final run status. Unanswered tool calls (e.g. after a cancel) get an error tool message so the stored history stays valid.

**Durable, multi-process execution:** no run state lives in API memory. Any number of API processes (`API_WORKERS`) and run workers can share one database; runs survive API restarts (verified end-to-end against Docker: disconnect → API restart → follow from the new instance → `completed`). In-flight state of a run that loses its *worker* is not resumable yet (it is reaped as failed); LangGraph checkpointing for resumable runs arrives with human approval (V2 Phase 6). The event protocol is specified in `API_DESIGN.md` §4. Because the runtime is transport-agnostic, WebSockets, a CLI or the future SDK can consume the same stream.

## 9. Deployment (Docker)

| Service | Image | Notes |
|---|---|---|
| `db` | `postgres:17-alpine` | Data in the `pgdata` volume; port bound to `127.0.0.1` |
| `backend` | `backend/Dockerfile` | Runs `alembic upgrade head`, then uvicorn (`API_WORKERS`, default 1; stateless); `RUN_WORKER_EMBEDDED=false`; `workspace/` mounted read-only at `/workspace`; health check on `/api/health` |
| `worker` | `backend/Dockerfile` | Same image, `python -m app.worker`: executes queued runs (`RUN_WORKER_CONCURRENCY`); starts after the API is healthy (migrations applied) |
| `frontend` | `frontend/Dockerfile` | Static build behind nginx; SPA fallback; `/api` proxied to `backend:8000` with `proxy_buffering off` and 1 h read timeout for SSE |

Inside Docker, `DATABASE_URL` and `OLLAMA_BASE_URL` are set explicitly in `docker-compose.yml`
(the dev `.env` values point at `127.0.0.1`, which inside a container is the container itself).

## 10. Extension points (postponed features)

| Future feature | Where it plugs in |
|---|---|
| More LLM providers | New factory in `runtime/providers/` |
| MCP tools | Adapter registering MCP tools into the tool registry |
| RAG | Retrieval exposed as tools |
| Human-in-the-loop / resume | Add `langgraph-checkpoint-postgres` + interrupts |
| Multi-agent | Agents as LangGraph subgraphs / agent-as-tool |
| Visual workflow editor | React Flow over a graph definition stored alongside agents |
| Multi-tenancy / auth | `owner_id` columns via migration + auth dependency in `api/deps.py` |
| UI SDK | Package `frontend/src/components/` |
