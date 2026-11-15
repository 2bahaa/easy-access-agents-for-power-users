# MVP Baseline (before V2)

Snapshot taken 2026-11-15 at commit `be5aa7f`, used to compare the system before and after the V2 upgrade.

## Quality gates at baseline
| Check | Result |
|---|---|
| Backend `uv run pytest` | 162 passed, 2 skipped (symlink tests on Windows without Developer Mode) |
| Frontend `npm run test` | 16 files, 93 tests passed |
| Frontend `typecheck` / `lint` / `build` | clean |
| Docker compose (db, backend, frontend) | all healthy |

## Capabilities
- Agents CRUD with per-agent model, params, system prompt, skills (ordered), tools (+config), `max_tool_calls`, `run_timeout_s`.
- One provider: Ollama (model discovery, `/api/show` capability detection: tools, thinking).
- Tools: `calculator` (AST whitelist), `file_reader` (workspace sandbox).
- Markdown skills (built-in seeded + user-created) injected into the system prompt.
- Custom LangGraph `StateGraph` agent ⇄ tools loop with our own tool node (limit → permission → args → config → timeout).
- Conversations, messages, runs (frozen `agent_snapshot`), persisted `run_events`.
- SSE streaming with 10 event types; cancel endpoint; disconnect cancels the run.
- Studio UI: agents list/editor, skills, tools, chat with run timeline; OS-driven dark mode.

## API surface (all under `/api`, unauthenticated)
`GET /health` · CRUD `/agents` · CRUD `/skills` · `GET /tools` · `GET /providers`, `GET /providers/{p}/models` · `GET|POST /conversations`, `GET|DELETE /conversations/{id}`, `POST /conversations/{id}/messages` (SSE) · `GET /runs/{id}`, `GET /runs/{id}/events`, `POST /runs/{id}/cancel`.

## Database (migration `20261114_0001`)
`agents`, `skills`, `agent_skills`, `agent_tools`, `conversations`, `runs`, `messages`, `run_events`. No ownership columns.

## Known limitations at baseline
- Active runs live in process memory → single worker; a restart fails in-flight runs; no SSE resume.
- No authentication, users or tenancy.
- One DB transaction per persisted event.
- No CI pipeline.
- Hardware: i7-7500U (2C/4T), 11.9 GB RAM, no NVIDIA GPU; local models `qwen3:4b`, `qwen2.5:3b`, `llama3.2:1b`.
