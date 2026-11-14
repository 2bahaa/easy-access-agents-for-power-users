# Easy Access Agents for Power Users

An Agent Studio for building, configuring and running your own AI agents:
pick a model, write instructions, attach Markdown skills, allow specific tools,
and watch tokens and tool calls stream live.

> Status: **Phase 4 — conversations & streaming done (backend MVP complete).** See the roadmap below.

Design docs: [Project spec](docs/PROJECT_SPEC.md) · [Architecture](docs/ARCHITECTURE.md) ·
[API design](docs/API_DESIGN.md) · [Implementation roadmap](docs/IMPLEMENTATION_ROADMAP.md)

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy 2 (async) + Alembic |
| Agent runtime | LangGraph 1.x (custom `StateGraph`), `langchain-ollama` |
| LLM | Ollama (local), behind a provider registry |
| Database | PostgreSQL 17 (Docker) |
| Streaming | Server-Sent Events |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Tests | pytest, Vitest + React Testing Library |

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (`pip install uv`, then use `uv` or `python -m uv`)
- Node.js 22+
- Docker Desktop (for PostgreSQL)
- [Ollama](https://ollama.com) running locally with a **tool-capable** model (see below)

## Setup

```bash
cp .env.example .env            # adjust passwords/ports
docker compose up -d db         # start PostgreSQL
cd backend
uv sync                         # create .venv and install deps
uv run alembic upgrade head     # create/upgrade the database schema
uv run uvicorn app.main:app --reload   # API on http://localhost:8000 (docs at /docs)
```

## Testing

```bash
cd backend
uv run pytest                   # needs the db container running
uv run ruff check . && uv run mypy app
```

Tests use a separate database (`<db>_test`, recreated and migrated on every run;
override with `TEST_DATABASE_URL`). Each test runs in a rolled-back transaction.

Symlink-escape tests for `file_reader` are skipped on Windows unless Developer Mode
is enabled. To run them in Linux (from `backend/`):

```bash
docker run --rm -v "$PWD:/app:ro" -w /app -e UV_PROJECT_ENVIRONMENT=/tmp/venv \
  ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
  sh -c "uv sync --frozen -q && uv run --frozen pytest -q -p no:cacheprovider tests/unit"
```

## Choosing an Ollama model

Agents need a model that supports **tool calling**. The runtime checks this
automatically via Ollama's `/api/show` (`capabilities` must include `"tools"`)
and refuses to run a tool-enabled agent on a model without it.

Advertised support is not the same as reliable behavior. Phase 0 spike results
(`backend/scripts/spike_ollama_tools.py`, 5 trials each, temperature 0):

| Model | `tools` capability | Correct tool call | Final answer uses result | Spurious tool calls on small talk | Token streaming |
|---|---|---|---|---|---|
| `llama3.2:1b` | yes | 5/5 | **0/5** | **5/5** | 5/5 |

Takeaways:
- The LangGraph + `ChatOllama` pipeline works end to end: tokens stream via
  `stream_mode="messages"` and tool events via `stream_mode="custom"`.
- `llama3.2:1b` calls tools but ignores their results and calls tools when not
  needed. Fine for wiring tests; not for real use.
- Recommended: `qwen3:8b` (or `qwen3:4b` on ≤8 GB VRAM). Re-run the spike to compare:
  `uv run python scripts/spike_ollama_tools.py qwen3:8b 5`

## Talking to an agent over HTTP

With the API running, create an agent and a conversation, then stream a message
(`-N` disables curl buffering so events appear live):

```bash
curl -s -X POST localhost:8000/api/agents -H 'content-type: application/json' \
  -d '{"name":"Math","model":"llama3.2:1b","tools":[{"name":"calculator"}]}'
curl -s -X POST localhost:8000/api/conversations -H 'content-type: application/json' \
  -d '{"agent_id":"<agent id>"}'
curl -N -X POST localhost:8000/api/conversations/<conversation id>/messages \
  -H 'content-type: application/json' -d '{"content":"What is 12 * 12?"}'
```

## Running an agent from the command line

You can also run the runtime directly against local Ollama, without the API (from `backend/`):

```bash
uv run python -m scripts.run_agent_live llama3.2:1b "What is 17.5 * 23 + 4?"
```

It prints every event (tool calls, results, final message, usage).

## Project layout

```
backend/     FastAPI app, agent runtime, tools, skills, migrations, tests
frontend/    React Agent Studio (Phase 5+)
workspace/   Sandbox folder — the only place the file_reader tool can read
```

## Roadmap

0. ✅ Scaffold & Ollama tool-calling spike
1. ✅ Backend foundation — config, DB, migrations, agents + skills CRUD
2. ✅ Tools — registry, calculator, sandboxed file reader
3. ✅ Runtime — provider registry, LangGraph loop, limits, events
4. ✅ Conversations & SSE streaming
5. Frontend Studio — agent builder, skills, tool picker
6. Frontend Chat — streaming chat + run timeline
7. Docker & docs
