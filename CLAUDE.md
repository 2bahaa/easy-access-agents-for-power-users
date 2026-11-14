# CLAUDE.md

Easy Access Agents for Power Users — an Agent Studio (React) + Agent Runtime (FastAPI + LangGraph) for building and running tool-using AI agents on local Ollama models.

Source of truth for design: `docs/PROJECT_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/API_DESIGN.md`, `docs/IMPLEMENTATION_ROADMAP.md`. Read the relevant doc before changing architecture, API contracts, the DB schema or the event protocol — and update the doc in the same change.

## Workflow
- Work one roadmap phase at a time. A phase is done only when its completion criteria in `docs/IMPLEMENTATION_ROADMAP.md` are met and all checks pass.
- Do not implement features listed as postponed in `docs/PROJECT_SPEC.md` (multi-agent, React Flow editor, MCP, RAG, multi-tenancy, advanced memory, SDK packaging).
- Do not add dependencies or abstractions not needed by the current phase. Justify any new dependency.

## Commands
Run from `backend/` (uv is invoked as `python -m uv` on this machine if `uv` is not on PATH):
- `uv sync` · `uv run pytest` · `uv run ruff check .` · `uv run ruff format .` · `uv run mypy app`
- `uv run alembic upgrade head` (Phase 1+)

Run from `frontend/`: `npm run dev` · `npm run test` · `npm run typecheck` · `npm run lint` · `npm run build`. Node 22.12+; `engine-strict` is on — check `engines` before adding/upgrading packages.

Infra: `docker compose up -d db` (PostgreSQL only, for local dev) · `docker compose up -d --build` (full stack: UI http://localhost:3000, API http://localhost:8001). Ollama runs on the host (`http://127.0.0.1:11434`; containers use `host.docker.internal`). Use `127.0.0.1`, not `localhost`, for local service URLs on this Windows machine (IPv6 `::1` causes 502s/2 s delays).

## Architecture constraints
- Layering: `api` → `services` → (`runtime`, `db`). Routers contain no business logic.
- `app/runtime/` must never import FastAPI or `app/db/`. It receives a resolved `AgentConfig` + message history and yields typed `AgentEvent`s.
- Orchestration uses a custom LangGraph `StateGraph` with our own tool node. Do not use `create_react_agent` or the prebuilt `ToolNode`.
- LLMs are created only through the provider registry (`app/runtime/providers/`).
- Tools are defined in code (`app/tools/`) and registered in the tool registry; per-agent permission and config live in the DB.
- Our Postgres tables are the single source of conversation history. No LangGraph checkpointer in the MVP.
- Schema changes go through Alembic migrations only — never `create_all` outside tests.
- The backend must run with a single worker (active runs live in process memory).
- SSE event types are a single Pydantic discriminated union mirrored by a TypeScript union. Change both together.
- UI components in `frontend/src/components/` are prop-driven (no data fetching inside) so they can become the SDK later. Data fetching lives in `features/` via the hooks in `api/queries.ts`.
- Use the semantic color tokens (`bg-surface`, `text-muted`, `border-line`, …) instead of raw grays so light/dark themes keep working.

## Coding conventions
- Python 3.12, full type hints, `mypy --strict` clean, ruff clean. Async I/O throughout (async SQLAlchemy, httpx).
- Pydantic v2 for API schemas, settings (`pydantic-settings`), tool args and tool configs.
- TypeScript `strict`; no `any` without a comment explaining why.
- Configuration and secrets come from environment variables only; keep `.env.example` updated. Never commit `.env`.

## Testing requirements
- Every feature ships with tests in the same change. Backend: pytest (unit + integration against Postgres). Frontend: Vitest + React Testing Library.
- Runtime tests use a scripted fake chat model — never a live Ollama call in the automated suite.
- Security-relevant code (tool validation, sandbox, limits) needs explicit negative tests.

## Security rules
- No tool may execute arbitrary code, shell commands or unrestricted network/filesystem access. No `eval`/`exec`.
- Before executing any tool call: check the tool is permitted for the agent, check call limits, validate args with the tool's Pydantic model, run with a timeout.
- `file_reader` reads only inside `WORKSPACE_DIR` (agents may narrow to a subfolder, never widen); reject traversal, absolute paths outside the root, symlink escapes, binary and oversized files.
- Enforce `max_tool_calls`, per-tool timeout and run timeout; agent values can never exceed the global caps from settings.
- Tool failures are returned to the model as tool messages and emitted as events; they must not crash the run or leak stack traces to clients.
- Refuse to run a tool-enabled agent on a model without the Ollama `tools` capability.
