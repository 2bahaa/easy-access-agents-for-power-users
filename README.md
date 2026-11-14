# Easy Access Agents for Power Users

An Agent Studio for building, configuring and running your own AI agents:
pick a model, write instructions, attach Markdown skills, allow specific tools,
and watch tokens and tool calls stream live.

> Status: **Phase 0 — scaffold & spike.** See the roadmap below.

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
uv run pytest                   # run tests
uv run ruff check . && uv run mypy app
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

## Project layout

```
backend/     FastAPI app, agent runtime, tools, skills, migrations, tests
frontend/    React Agent Studio (Phase 5+)
workspace/   Sandbox folder — the only place the file_reader tool can read
```

## Roadmap

0. ✅ Scaffold & Ollama tool-calling spike
1. Backend foundation — config, DB, migrations, agents + skills CRUD
2. Tools — registry, calculator, sandboxed file reader
3. Runtime — provider registry, LangGraph loop, limits, events
4. Conversations & SSE streaming
5. Frontend Studio — agent builder, skills, tool picker
6. Frontend Chat — streaming chat + run timeline
7. Docker & docs
