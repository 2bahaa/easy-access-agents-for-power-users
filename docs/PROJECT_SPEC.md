# Project Specification

**Product:** Easy Access Agents for Power Users
**Status:** Approved for MVP · Phase 0 complete

## 1. Vision

An Agent Studio that lets technically capable users create, configure, test and run their own AI agents through a visual interface. Users choose a model, write instructions, attach reusable skills, grant specific tools, and watch the agent reason, call tools and answer in real time. Over time the UI becomes a reusable React SDK.

## 2. Product components

| Component | Responsibility | MVP? |
|---|---|---|
| **Agent Studio** | Web UI to create/configure agents, manage skills, chat, inspect runs | Basic version |
| **Agent Runtime** | Loads agent config, builds prompts with skills, binds permitted tools, runs the LLM/tool loop, enforces limits, streams events | Yes |
| **Agent UI SDK** | Reusable components: `AgentBuilder`, `AgentChat`, `ToolPicker`, `SkillSelector`, `AgentRunTimeline` | Built as internal prop-driven components; packaging postponed |

## 3. Users and assumptions

- **Single user, no authentication** in the MVP. The schema allows adding ownership later via migration.
- Users run Ollama locally and can pull models.
- Users are technical: they can edit system prompts and Markdown and understand tool permissions.

## 4. Functional requirements (MVP)

1. **Agents** — create, edit, list, retrieve, delete. Fields: name, description, provider, model, model parameters, system prompt, attached skills, permitted tools with per-tool config, `max_tool_calls`, `run_timeout_s`.
2. **Providers & models** — provider abstraction; initial provider is Ollama. List local models with their tool/thinking capability.
3. **Skills** — reusable Markdown documents (name, slug, description, content) managed in a library and attached to agents in order. Built-in skills are seeded from `backend/skills/*.md`. MVP injects attached skills into the system prompt.
4. **Tool library** — tools defined in code with standard JSON schemas generated from Pydantic models. MVP tools:
   - `calculator` — safe arithmetic evaluator (AST-based, no `eval`).
   - `file_reader` — read-only text file access restricted to the workspace sandbox.
5. **Tool permissions** — each agent enables a subset of tools; only those are bound to the model and executable.
6. **Execution** — real agent loop with dynamic tool calling until the model answers without tool calls or a limit is hit.
7. **Streaming** — live response tokens, optional reasoning tokens, and tool/run status events over SSE.
8. **Conversations** — persisted conversations, messages, runs and run events; reloadable after restart.
9. **Studio UI** — agent list/editor, skill library, tool picker, chat with streaming and a run timeline.

## 5. Non-functional requirements

- Modular layered architecture (API, services, runtime, tools, skills, DB, streaming).
- Typed Python (`mypy --strict`) and TypeScript (`strict`); Pydantic validation for config and APIs.
- Configuration and secrets via environment variables; `.env.example` maintained.
- Database migrations via Alembic.
- Automated tests from the start (pytest, Vitest).
- Docker Compose for PostgreSQL from the start; full stack containers in the final MVP phase.
- Installation, configuration and execution documented in `README.md`.

## 6. Safety requirements

- No unrestricted code execution or OS access by agents.
- Tool arguments validated and permissions checked before execution.
- Limits: max tool calls per run, per-tool timeout, overall run timeout; agent values capped by global settings.
- Tool errors returned to the model and surfaced as events, never crashing the run.
- Tool-enabled agents refused on models lacking the Ollama `tools` capability.

## 7. Model capability findings (Phase 0)

Ollama advertises tool support via `/api/show` → `capabilities`. Advertised support ≠ reliable behavior. Spike with `llama3.2:1b` (5 trials): correct tool call 5/5, final answer used tool result 0/5, spurious tool calls on small talk 5/5, token streaming 5/5. Conclusion: the pipeline works; small models are suitable only for wiring tests. Recommended models: `qwen3:8b` or `qwen3:4b`. The model is per-agent configuration, never hard-coded.

## 8. Out of scope for MVP (postponed)

Multi-agent collaboration · drag-and-drop workflow editor (React Flow) · MCP integrations · advanced RAG · production multi-tenant deployment · advanced persistent memory · reusable UI SDK packaging · unrestricted Python execution · authentication.

The architecture must allow these later without a rewrite (see `ARCHITECTURE.md` §9).

## 9. MVP acceptance criteria

1. Create, edit, list and delete agents via the UI; provider and model are selected from the live Ollama model list, which shows a tool-support badge.
2. Create and edit Markdown skills and attach them to agents; attached skill content verifiably reaches the system prompt (unit test).
3. The ToolPicker lists registry tools with descriptions; per-agent enablement and config (e.g. `file_reader` subfolder) are persisted.
4. Chatting with an agent streams tokens live; asking "what is 17.5 * 23 + 4?" triggers `calculator`, and the timeline shows started/completed events with args and result.
5. Reading `notes.txt` from the workspace works; `../` traversal, absolute paths outside the sandbox, symlink escapes, and oversized or binary files are rejected with `tool.call.failed`.
6. A tool not enabled for the agent is never bound to the model and is rejected if the model calls it anyway.
7. `max_tool_calls`, per-tool timeout and `run_timeout_s` are enforced (automated tests with a fake model).
8. Conversations and run timelines persist and reload after a page refresh and server restart.
9. Running a tool-enabled agent on a model without tool capability is blocked with a clear error.
10. `pytest` and `vitest` pass; Alembic migrations build the schema from an empty database; `docker compose up` runs the full stack; `README.md` covers setup.

Criterion 4 requires a model that reliably uses tool results (e.g. `qwen3:4b`/`qwen3:8b`); with `llama3.2:1b` only the tool call and events are verifiable.
