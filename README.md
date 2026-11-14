# Easy Access Agents for Power Users

An Agent Studio for building, configuring and running your own AI agents on local
models: pick a model, write instructions, attach Markdown skills, allow specific tools,
and watch tokens and tool calls stream live.

> Status: **MVP complete** (roadmap phases 0–7). See [acceptance results](docs/IMPLEMENTATION_ROADMAP.md#mvp-acceptance-results).

Design docs: [Project spec](docs/PROJECT_SPEC.md) · [Architecture](docs/ARCHITECTURE.md) ·
[API design](docs/API_DESIGN.md) · [Implementation roadmap](docs/IMPLEMENTATION_ROADMAP.md)

## Features

- **Agent Studio** — create agents with a model, system prompt, ordered skills, permitted
  tools (with per-agent settings) and safety limits. The model picker shows which local
  models support tool calling.
- **Streaming chat** — tokens stream live; tool calls appear inline; a **run timeline**
  shows every step (arguments, results, errors, timing, tokens). Stop a run at any time.
- **Safe tools** — a calculator (no `eval`) and a read-only file reader confined to
  `workspace/`. Every call is permission-checked, validated, time-limited and counted.
- **History** — conversations, messages and run timelines are stored in PostgreSQL.

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy 2 (async), Alembic |
| Agent runtime | LangGraph 1.x (custom `StateGraph`), `langchain-ollama` |
| LLM | Ollama on the host, behind a provider registry |
| Database | PostgreSQL 17 |
| Streaming | Server-Sent Events |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4, TanStack Query |
| Tests | pytest (162), Vitest + React Testing Library (84) |

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Ollama](https://ollama.com) running on this machine with a **tool-capable** model, e.g.
  `ollama pull qwen3:4b` (see [Choosing a model](#choosing-an-ollama-model))
- For local development only: Python 3.12+ with [uv](https://docs.astral.sh/uv/)
  (`pip install uv`, then `uv` or `python -m uv`) and Node.js 22.12+

## Quick start (Docker)

```bash
cp .env.example .env              # then change POSTGRES_PASSWORD (and DATABASE_URL to match)
docker compose up -d --build      # database + API + Studio
```

Open **http://localhost:3000**. Migrations run automatically when the backend starts.

| URL | What |
|---|---|
| http://localhost:3000 | Agent Studio (nginx; proxies `/api` to the backend) |
| http://localhost:8001/docs | API docs (OpenAPI) |
| `127.0.0.1:5432` | PostgreSQL |

All ports are bound to `127.0.0.1` only. Change them with `FRONTEND_PORT`, `BACKEND_PORT`
and `POSTGRES_PORT` in `.env`.

```bash
docker compose logs -f backend    # follow API logs
docker compose stop backend frontend   # stop the app, keep the database running
docker compose down               # stop everything (data stays in the pgdata volume)
```

The containers reach Ollama on the host via `host.docker.internal:11434`. The
`workspace/` folder is mounted **read-only** at `/workspace`; put files there for the
file reader tool.

## Local development

Run the database in Docker and the API/Studio on your machine (hot reload).

```bash
docker compose up -d db
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload      # API on http://localhost:8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev                               # Studio on http://localhost:5173
```

> **Run backend commands from `backend/`.** `uv run` finds the project by its
> `pyproject.toml` there. From the repo root, use
> `uv run --directory backend uvicorn app.main:app --reload`.

The Vite dev server proxies `/api` to `http://127.0.0.1:8000` (override with
`VITE_PROXY_TARGET` in `frontend/.env`).

## Using the Studio

1. **Agents → New agent**: pick a model (look for the **Tools** badge), write instructions,
   attach skills and enable tools, then **Create agent**.
2. Click **Chat** on the agent card (or **Open chat** in the editor).
3. Send a message. Tool calls appear inline and step by step in the **Run timeline**
   (right panel, or the activity icon on smaller screens).
4. **Stop** cancels the run. Leaving the chat page while a run is streaming also cancels it.

You can also drive agents over HTTP (`-N` disables curl buffering so events appear live):

```bash
curl -s -X POST localhost:8000/api/agents -H 'content-type: application/json' \
  -d '{"name":"Math","model":"qwen3:4b","tools":[{"name":"calculator"}]}'
curl -s -X POST localhost:8000/api/conversations -H 'content-type: application/json' \
  -d '{"agent_id":"<agent id>"}'
curl -N -X POST localhost:8000/api/conversations/<conversation id>/messages \
  -H 'content-type: application/json' -d '{"content":"What is 12 * 12?"}'
```

(Use port 8001 for the Docker stack.) To run the runtime directly without the API:
`uv run python -m scripts.run_agent_live <model> "<question>"` from `backend/`.

## Configuration

All settings come from environment variables (`.env`, see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `eaa` / `change-me` / `eaa` | Database credentials (Docker) |
| `DATABASE_URL` | `postgresql+asyncpg://…@127.0.0.1:5432/eaa` | Local-dev DB connection |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama for local dev |
| `DOCKER_OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama as seen from the backend container |
| `WORKSPACE_DIR` | `../workspace` | Root folder for the file reader (Docker: `/workspace`, read-only) |
| `MAX_TOOL_CALLS_CAP` / `RUN_TIMEOUT_CAP_S` / `TOOL_TIMEOUT_S` | `20` / `300` / `10` | Global safety caps; agents can only set lower values |
| `FRONTEND_PORT` / `BACKEND_PORT` | `3000` / `8001` | Host ports for the Docker stack |

## Testing

```bash
cd backend && uv run pytest && uv run ruff check . && uv run mypy app   # needs the db container
cd frontend && npm run test && npm run lint && npm run typecheck && npm run build
```

Backend tests use a separate database (`<db>_test`, recreated and migrated on every run),
a scripted fake model (no Ollama needed) and roll back every test. Symlink-escape tests
for the file reader are skipped on Windows without Developer Mode; run them on Linux
from `backend/`:

```bash
docker run --rm -v "$PWD:/app:ro" -w /app -e UV_PROJECT_ENVIRONMENT=/tmp/venv \
  ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
  sh -c "uv sync --frozen -q && uv run --frozen pytest -q -p no:cacheprovider tests/unit"
```

## Choosing an Ollama model

Agents with tools need a model with the Ollama **tools** capability; the Studio shows a
badge and the backend refuses tool-enabled agents on models without it. Advertised
support is not the same as reliable behavior. Observed with `llama3.2:1b`:

| Check | Result |
|---|---|
| Calls the calculator correctly | yes (consistently) |
| Uses the tool result in its final answer | often not (e.g. "406.5 … adding 4 gives 410.5") |
| Calls tools on small talk | yes |
| File reader calls | malformed (schema echo, wrong tool, or JSON as text) |

The platform handles these safely (validation errors are returned to the model and shown
in the timeline), but for useful agents use **`qwen3:4b`** (≤ 8 GB VRAM) or **`qwen3:8b`**.
Compare models with `uv run python scripts/spike_ollama_tools.py <model> 5` (from `backend/`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No module named 'app'` | Run backend commands from `backend/` (see above). |
| `ports are not available … bind` when starting Docker | Another program uses the port, or Windows reserved it (`netsh interface ipv4 show excludedportrange protocol=tcp`). Set a different `FRONTEND_PORT` / `BACKEND_PORT` in `.env`. |
| Studio dev server shows 502 for `/api` | Keep proxy targets on `127.0.0.1`, not `localhost` (Node resolves `localhost` to IPv6 `::1`, uvicorn listens on IPv4). |
| Every DB request takes ~2 s on Windows | Use `127.0.0.1` instead of `localhost` in `DATABASE_URL` (the port is published on IPv4 only). |
| Sidebar shows **Ollama: Offline** | Start Ollama. On Linux hosts, Ollama may need `OLLAMA_HOST=0.0.0.0` to accept connections from containers. |
| First message takes a long time | Ollama loads the model into memory on first use after being idle. |
| Agent answers wrongly despite correct tool results | Model quality; see [Choosing a model](#choosing-an-ollama-model). |

## Project layout

```
backend/     FastAPI app, agent runtime, tools, skills, migrations, tests, Dockerfile
frontend/    React Agent Studio, nginx config, Dockerfile
workspace/   Sandbox folder: the only place the file reader can read (read-only in Docker)
docs/        Spec, architecture, API design, roadmap
```

## Roadmap

0. ✅ Scaffold & Ollama tool-calling spike
1. ✅ Backend foundation — config, DB, migrations, agents + skills CRUD
2. ✅ Tools — registry, calculator, sandboxed file reader
3. ✅ Runtime — provider registry, LangGraph loop, limits, events
4. ✅ Conversations & SSE streaming
5. ✅ Frontend Studio — agent builder, skills, tool picker
6. ✅ Frontend Chat — streaming chat + run timeline
7. ✅ Docker & docs

Next (post-MVP, see `docs/ARCHITECTURE.md` §10): more providers, MCP tools, RAG,
human-in-the-loop, multi-agent, visual workflow editor, auth, SDK packaging.
