# Implementation Roadmap

Each phase ends with all checks green and a commit. **Standard checks:** backend `uv run ruff check .`, `uv run mypy app`, `uv run pytest`; frontend (Phase 5+) `npm run lint`, `npm run test`, `npm run build`. "AC n" refers to the acceptance criteria in `PROJECT_SPEC.md` §9.

## Phase 0 — Scaffold & Ollama spike ✅ (done)
- Repo layout, `.gitignore`, `.env.example`, `docker-compose.yml` (Postgres), uv project, ruff/mypy/pytest config, `workspace/` sandbox.
- Spike: LangGraph custom graph + `ChatOllama.bind_tools`, streamed tokens and custom tool events.

**Done when:** checks pass; spike results recorded in `README.md`. ✅ (`llama3.2:1b`: pipeline works, model quality insufficient for real use.)

## Phase 1 — Backend foundation
- `config.py` (pydantic-settings), async DB session, SQLAlchemy models for all tables in `ARCHITECTURE.md` §5, initial Alembic migration.
- App factory, CORS, problem-JSON error handling, `GET /health`.
- Skills CRUD + seeding from `backend/skills/*.md` (one example built-in skill).
- Agents CRUD with `skill_ids`; `tools` field stored but validated in Phase 2; limits capped by global settings.
- Test infrastructure: Postgres test database, transactional fixtures, httpx `AsyncClient`.

**Done when:** `alembic upgrade head` on an empty DB and `downgrade base` both work; CRUD integration tests for agents and skills pass (create, read, update, delete, 404, 422, duplicate slug 409).

## Phase 2 — Tools
- `Tool` base (Args/Config Pydantic models, timeout, async `run`), tool registry, `GET /tools`.
- `calculator`: AST-based evaluator (numbers, + − × ÷ ** %, parentheses, unary minus; bounded exponent/length).
- `file_reader`: sandbox under `WORKSPACE_DIR`, optional per-agent `subdir`, size limit, UTF-8 only.
- Agent service validates tool names against the registry and configs against each tool's `Config`.

**Done when:** unit tests cover valid and malicious calculator input (e.g. `__import__`, names, attribute access, huge powers) and file_reader rejection cases (traversal, absolute path, symlink escape, oversized, binary, subdir escape) — AC 5 at unit level; unknown tool / bad config return 422.

## Phase 3 — Agent runtime
- Provider registry + Ollama factory; capability lookup via `/api/show`; `GET /providers`, `GET /providers/{provider}/models`.
- Skill prompt composition.
- `AgentEvent` union; LangGraph `StateGraph` (`agent` ⇄ `tools`); tool node (permission → limit → validation → timeout → events); effective limits; run timeout; `run_agent()` async generator.

**Done when:** runtime tests with a scripted fake chat model prove: tokens → `message.delta`; tool call → started/completed events and `ToolMessage`; validation/permission/timeout failures returned to the model; `max_tool_calls` → `limit_exceeded`; run timeout → `timeout`; unpermitted tool never bound (AC 6, AC 7); skills appear in the system prompt (AC 2); model without `tools` capability → `model_no_tool_support` (AC 9). Optional manual check against live Ollama.

## Phase 4 — Conversations & streaming
- Conversation CRUD; run service (snapshot, persistence of messages, run events, status, usage).
- `POST /conversations/{id}/messages` SSE endpoint (`sse-starlette`), keep-alives, disconnect → cancel; `GET /runs/{id}`, `GET /runs/{id}/events`, `POST /runs/{id}/cancel`.

**Done when:** integration tests over the SSE stream (fake model injected via the provider registry) verify event order, single terminal event, persisted messages and events, history included on the next turn, cancellation; data survives app restart (AC 8, backend part).

## Phase 5 — Frontend Studio
- Vite + React + TS + Tailwind scaffold, React Router, TanStack Query, API client and types.
- Agents list and editor (`AgentBuilder`), model picker with tool-support badge, `SkillSelector`, `ToolPicker` with per-tool config, skills library page.

**Done when:** AC 1, AC 2 (UI part) and AC 3 work against the running backend; Vitest + RTL tests cover AgentBuilder form validation, ToolPicker and SkillSelector.

## Phase 6 — Frontend Chat
- SSE parser, run-event reducer, `AgentChat` with live tokens, `AgentRunTimeline`, conversation sidebar, cancel button, reload of history and timelines.

**Done when:** AC 4 and AC 8 pass manually with a tool-capable model; Vitest tests cover the SSE parser (chunk boundaries, multi-line data) and the event reducer.

## Phase 7 — Docker & documentation
- Backend and frontend Dockerfiles; compose runs db + backend (migrations on start) + frontend; backend reaches host Ollama via `host.docker.internal`.
- README: install, configuration, running locally and via Docker, testing, model selection.

**Done when:** `docker compose up` starts the full stack from a clean checkout; a full manual pass of AC 1–10 succeeds.

## Acceptance criteria coverage

| AC | Phase(s) |
|---|---|
| 1 Agent CRUD + model picker | 1, 3, 5 |
| 2 Skills attached → system prompt | 1, 3, 5 |
| 3 ToolPicker + per-agent config | 2, 5 |
| 4 Streaming chat + calculator timeline | 3, 4, 6 |
| 5 file_reader sandbox | 2, 3 |
| 6 Unpermitted tool never bound/executed | 3 |
| 7 Limits and timeouts | 3 |
| 8 Persistence across restart | 4, 6 |
| 9 Non-tool model blocked | 3 |
| 10 Tests, migrations, Docker, README | all, 7 |

## After the MVP (not scheduled)
Multi-agent, React Flow editor, MCP tools, RAG, HITL with checkpointer, more providers, auth/multi-tenancy, advanced memory, SDK packaging — see `ARCHITECTURE.md` §9.
