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
| Streaming | SSE via `sse-starlette`; frontend `fetch` + small SSE parser | One POST per turn streams its run; no job queue needed |
| Frontend | React, TypeScript, Vite, Tailwind CSS v4, React Router, TanStack Query | Standard and minimal |
| Tooling | uv, ruff, mypy, pytest, pytest-asyncio, httpx; Vitest, React Testing Library | |
| Containers | Docker Compose: Postgres now, backend/frontend in Phase 7; Ollama on host | GPU passthrough on Windows is impractical |

Verified versions (Phase 0): Python 3.12, LangGraph 1.2.22, langchain-core 1.8, langchain-ollama 1.1.0, Ollama 0.40.

## 3. Component responsibilities

### Backend (`backend/app/`)
| Module | Responsibility |
|---|---|
| `main.py` | App factory, lifespan (DB engine, registries, skill seeding), CORS, router mounting |
| `config.py` | `Settings` from environment: DB URL, Ollama URL, `WORKSPACE_DIR`, global caps |
| `api/routers/` | HTTP endpoints only: parse/validate, call a service, map results/errors |
| `api/sse.py` | Serialize `AgentEvent`s to SSE frames, keep-alives, disconnect → cancel |
| `api/errors.py` | Domain exceptions → problem-JSON responses |
| `schemas/` | Pydantic request/response models |
| `services/` | Use cases: agent/skill CRUD with validation, conversation management, run orchestration (build `AgentConfig`, persist messages/events/status) |
| `db/` | SQLAlchemy models and async engine/session factory. Services query via the session directly; a repository layer is added only if query logic starts to repeat |
| `runtime/providers/` | `Provider` protocol (list models, capabilities, build chat model, classify provider errors), registry, Ollama implementation |
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
| `api/` | REST client, SSE parser, TS types mirroring backend schemas and events |
| `features/` | Data-fetching containers per domain: agents, skills, chat, runs |
| `components/` | Prop-driven SDK candidates: `AgentBuilder`, `ToolPicker`, `SkillSelector`, `AgentChat`, `AgentRunTimeline` |
| `pages/`, `routes.tsx` | Routing and page layout |

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
2. `run_service` loads agent, skills and tool configs → immutable `AgentConfig`; creates a `runs` row with `agent_snapshot`; persists the user message.
3. **Pre-flight:** provider resolves the model; if the agent has tools and the model lacks the `tools` capability → `run.failed` (`model_no_tool_support`).
4. Compose system prompt (agent prompt + skills). Bind only permitted tool schemas.
5. **Graph loop** (`graph.astream(..., stream_mode=["messages", "custom"], version="v2")`):
   - `agent` node calls the LLM; token chunks with `langgraph_node == "agent"` → `message.delta` (thinking → `reasoning.delta`).
   - If tool calls → `tools` node, per call (events go through the LangGraph stream writer):
     a. `tool_call_count < max_tool_calls`? else end the run: status `limit_exceeded`, `run.failed`
     b. emit `tool.call.started`
     c. tool permitted for this agent? else `tool.call.failed` (`permission`)
     d. validate args with `Args` → on error `tool.call.failed` (`validation`)
     e. `asyncio.wait_for(tool.run(...), timeout_s)` → `tool.call.completed`, or `tool.call.failed` (`timeout`/`execution`)
     f. append a `ToolMessage` with the result or a user-safe error, so the model can recover
   - Loop until the model replies without tool calls; LangGraph `recursion_limit` is derived from `max_tool_calls` as a backstop.
6. The whole run is wrapped in `asyncio.timeout(run_timeout_s)` → status `timeout`.
7. Persist assistant/tool messages, run events and final status/usage; emit exactly one terminal event.
8. Client disconnect or `POST /runs/{id}/cancel` cancels the run task → status `cancelled`.

## 8. Streaming design

The graph runs in a producer task that feeds a queue; `AgentRun.stream()` reads the queue. The run timeout and cancellation therefore apply only to agent work, never to the consumer's code, and an early consumer exit (client disconnect) cancels the run. Graph streaming uses `stream_mode=["messages", "custom", "updates"]` (`version="v2"`): `messages` → token deltas, `custom` → tool events from the tool node's stream writer, `updates` → completed messages, usage and tool-call counts.

When `max_tool_calls` is reached, pending tool calls still receive an error `ToolMessage` so stored history remains well-formed, then the run ends with `limit_exceeded`.

The runtime yields `AgentEvent` objects (Pydantic discriminated union in `runtime/events.py`). The run service fans them out to (a) the SSE response and (b) a persister that writes every non-delta event to `run_events`. The event protocol is specified in `API_DESIGN.md` §4. Because the runtime is transport-agnostic, WebSockets, a CLI or the future SDK can consume the same stream.

## 9. Extension points (postponed features)

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
