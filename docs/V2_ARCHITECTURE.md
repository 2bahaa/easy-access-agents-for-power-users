# V2 Architecture & Roadmap (approved 2026-11-15)

## Context
The MVP is finished: roadmap phases 0–7 are done, all 10 acceptance criteria pass, the backend has about 108 tests and the frontend about 87. V2 turns it into a platform with several providers, MCP, knowledge/RAG, visual workflows, multi-agent systems, human approval, an SDK and multiple tenants. Most of those are listed as *postponed* in `docs/PROJECT_SPEC.md` §8 and forbidden by `CLAUDE.md:9`, so Phase 0 has to formally reopen that scope in the docs before any code is written.
This document is based on a read-only audit of the repository. Nothing has been modified.

---

## 1. MVP audit (verified in the code)

### 1.1 Implemented and working: reuse as is
| Area | What exists | Where |
|---|---|---|
| Layering | api → services → (runtime, db); runtime does not depend on FastAPI or the database | `backend/app/` |
| Agent loop | Custom `StateGraph` (agent ⇄ tools), run timeout, `recursion_limit`, one terminal event per run | `runtime/graph.py`, `runtime/executor.py` (`AgentRun`) |
| Tool node | Checks in order: call limit → permission → Pydantic args → per-agent config → `wait_for` timeout; failures go back to the model as messages; fixes models that echo the schema back | `runtime/tool_node.py` |
| Limits | Agent limits clamped to the global caps | `runtime/limits.py` (`effective_limits`) |
| Event protocol | Discriminated union of 10 event types, mirrored in TypeScript | `runtime/events.py`, `frontend/src/api/events.ts` |
| Provider abstraction | `Provider` protocol with a registry; Ollama capabilities read from `/api/show` | `runtime/providers/{base,ollama,registry}.py` |
| Tools | `Tool[Args,Config]` contract; `calculator` (whitelisted AST), `file_reader` (hardened sandbox) | `app/tools/` |
| Skills | Markdown with frontmatter; built-ins seeded; ordered per agent; added to the system prompt | `app/skills/`, `skill_service` |
| Persistence | 8 tables; `agent_snapshot` frozen on each run; `run_events` saved; interrupted runs marked failed at startup | `db/models.py`, `run_service` |
| SSE | `id: seq` frames, 15 s ping, cancel when the client disconnects | `api/sse.py` |
| Errors | RFC 7807 problem JSON; domain error → HTTP code mapping | `api/errors.py`, `services/errors.py` |
| Frontend | React 19, Vite 8, Tailwind v4 tokens, TanStack Query v5, prop-driven `components/`, hand-written safe Markdown, SSE parser, `runReducer` | `frontend/src/` |
| Infra | Docker compose for db, backend and frontend; non-root images; nginx with SSE buffering off | `docker-compose.yml` |

### 1.2 Partial: needs modification
- **Providers:** Ollama only. Parameters are Ollama-specific (`num_ctx`, `think`). No credential model.
- **Tool registry:** code-only and built once at startup. `agent_tools.tool_name` has no namespace, so names could collide once MCP tools exist.
- **Skills:** prompt text only. No versions, tags or import/export. Slugs are unique across the whole system, not per tenant.
- **Run lifecycle:** the run lives inside an asyncio task. Messages are written only when the run finishes, so a crash mid-run loses them. Closing the tab cancels the run. There is no reconnect (`Last-Event-ID` is ignored).
- **Theme:** dark mode follows only the OS setting. No status tokens (raw emerald/red colours).
- **UI primitives:** hand-rolled. No dialog/popover/tooltip/menu/tabs/combobox, no focus trapping, no command palette. Only three navigation items.
- **Chat:** no syntax highlighting, tables or GFM.

### 1.3 Missing for V2
Authentication, users, organizations, RBAC; additional providers and stored credentials; MCP; custom tools; agent versions and drafts; knowledge/RAG and memory; workflows (model, editor, executor); multi-agent; approvals (pause/resume); dashboard and analytics; SDK package; CI; observability.

### 1.4 Risks and debt (ranked)
1. **Runs live in process memory** (`RunManager._active`, `--workers 1`). This blocks pause/resume, approvals that outlast the connection, workflows and scaling. **This is the most important thing to fix.**
2. **No authentication or tenancy:** every endpoint is open. `WORKSPACE_DIR`, the registries and skill slugs are global.
3. **One database transaction per event:** too chatty once workflows and multi-agent runs produce far more events.
4. `--forwarded-allow-ips="*"` trusts any proxy. No rate limits or request size limits in the API (nginx caps bodies at 1 MB).
5. No CI. The symlink-escape tests are skipped on Windows.
6. **Hardware:** i7-7500U (2 cores), 11.9 GB RAM, no NVIDIA GPU. Local models top out around `qwen3:4b` (installed). Local embeddings must be small (`nomic-embed-text` or `all-minilm` through Ollama). Cloud providers become important for quality, and automated tests must never call any real model.

---

## 2. Target V2 architecture

```
frontend/ (Studio app)  ──imports──▶  packages/agent-ui (SDK: components, types, theme)
        │ REST + SSE (/api/v2…, /api kept as is)
backend/app
  api/routers   → auth dependency → services (authz: org, workspace, role)
  services      → runtime | db | integrations
  runtime/      (still no FastAPI/db imports)
     agent/     current agent graph, generalised (tools node, approval interrupt)
     workflow/  compiler: validated WorkflowSpec → LangGraph StateGraph
     multiagent/ supervisor / sequential / parallel patterns compiled to subgraphs
     providers/ ollama, openai, anthropic, gemini, openai_compatible(HF, vLLM, LM Studio)
  tools/        native tools + CapabilityRegistry (native | mcp | http custom)
  integrations/mcp/  MCP client sessions (official `mcp` SDK), per-server pool
  knowledge/    ingest → chunk → embed (provider registry) → pgvector; hybrid retrieval
  worker/       run executor (same image, separate process), Postgres-backed queue
```

**Key decisions**
- **Durable execution (fixes risk 1).** A run becomes a row in a Postgres job queue (`SELECT … FOR UPDATE SKIP LOCKED`). A separate worker process executes it. LangGraph's `langgraph-checkpoint-postgres` saves graph state so a run can pause (`interrupt()` for approvals) and resume, even after a restart. Events are written in batches and fanned out through Postgres `LISTEN/NOTIFY`. The API's SSE endpoint just tails events and supports `Last-Event-ID` resume, so **disconnecting no longer cancels the run** and cancelling is a database flag the worker checks. This replaces the "no checkpointer" rule. Our tables stay the source of truth for conversation history; the checkpointer holds only state for runs that are still in progress, and is cleared when a run finishes. No Redis/Celery is needed, which keeps the infrastructure to Postgres alone.
- **pgvector** in the existing Postgres (image `pgvector/pgvector:pg17`) rather than a separate vector database. Hybrid search = pgvector cosine + Postgres `tsvector` full-text, merged with reciprocal rank fusion (RRF). Reranking is optional and off by default.
- **Authentication:** built-in email/password (argon2) with short-lived JWT access tokens and refresh cookies, plus personal API keys for SDK/server use. A pluggable OIDC option comes later. Hierarchy: Organization → Workspace → resources. Roles: owner / admin / editor / viewer. **Every query is scoped by `workspace_id` in the service layer**, and negative tests check that one tenant cannot reach another's data. Postgres row-level security is a possible later hardening step.
- **Secrets:** `provider_connections` and `mcp_servers` credentials are encrypted at rest with an envelope key (`cryptography` Fernet) from the `SECRET_ENCRYPTION_KEY` env var. They are never returned to the client, which only sees `has_secret: true` and the last 4 characters.
- **API compatibility:** existing `/api/*` contracts keep working (the MVP UI and tests stay green). New resources are added alongside them. Breaking changes are versioned, never made silently.

---

## 3. Database evolution (Alembic, additive migrations, one per phase)
- **Tenancy (Phase 2):** `organizations`, `users`, `memberships(org, user, role)`, `workspaces`, `api_keys(hash)`, `refresh_tokens`. Add `workspace_id` (FK, indexed) to agents, skills, conversations, runs. A migration backfills a "Default" org and workspace that own the existing rows.
- **Providers:** `provider_connections(id, workspace_id, kind, name, base_url, secret_enc, status, last_checked_at)`, `models_cache(connection_id, model_id, capabilities jsonb, context_window, fetched_at)`. `agents.provider` becomes `agents.connection_id` (backfilled to an Ollama connection).
- **Agent versions:** `agent_versions(agent_id, version, state draft|published, config jsonb, created_by, created_at)`. `agents.published_version_id`. Runs reference `agent_version_id`, alongside the existing snapshot.
- **Capabilities:** `mcp_servers(workspace_id, name, transport stdio|streamable_http, command/args or url, env_enc, enabled, status)`, `mcp_tools(server_id, name, schema jsonb, enabled)`, `custom_tools(workspace_id, kind http, spec jsonb)`. `agent_tools.tool_name` becomes a namespaced `tool_ref` (`native:calculator`, `mcp:<server>/<tool>`, `custom:<id>`).
- **Skills:** add `workspace_id`, `version`, `tags text[]`, `category`; make the slug unique per workspace; add a `skill_versions` table.
- **Knowledge and memory:** `knowledge_collections`, `documents(status, sha256, mime, size)`, `chunks(document_id, ord, text, tsv tsvector, embedding vector(n), meta jsonb)` with HNSW and GIN indexes; `agent_knowledge(agent_id, collection_id)`; `memories(scope user|agent|session, owner ids, content, embedding, created_at)`.
- **Workflows:** `workflows(workspace_id, name)`, `workflow_versions(spec jsonb, schema_version, state)`, `node_runs(run_id, node_id, agent_id?, status, input_redacted, output_redacted, started_at, finished_at)`. `runs` gains `kind agent|workflow|team`, `parent_run_id`, `workflow_version_id`, `depth`, and the statuses `queued` / `waiting_approval`.
- **Approvals:** `approval_policies(workspace_id, scope agent|tool, rule jsonb)`, `approval_requests(run_id, node_id, tool_ref, args_redacted, proposed_args, status, decided_by, decided_at, expires_at)`.
- **Audit:** `audit_log(workspace_id, actor_id, action, target, meta, ts)`.
- **Strategy:** expand/contract (add nullable → backfill → enforce NOT NULL). `test_migrations` runs upgrade from an empty database and checks downgrade for each new revision.

---

## 4. Visual workflow execution architecture
- **WorkflowSpec** is a Pydantic model and the only contract: `nodes[{id, type, config}]`, `edges[{source, sourceHandle, target}]`, `variables`, `schema_version`. The frontend's React Flow JSON is converted to the spec, **and the server re-validates everything**: node types come from a backend registry; each node's config is checked against its Pydantic model; the graph must be a DAG apart from explicit loop nodes with an iteration cap; it must be reachable from Start and terminate at End; tool and agent refs must belong to the workspace and be permitted; variable references must resolve.
- **Node registry** (`runtime/workflow/nodes/`): start, end, agent (runs the existing agent subgraph), llm, tool, mcp_tool, skill (adds prompt context), knowledge_retrieve, memory_read/write, condition (a safe expression language: JSONPath plus comparisons, no eval), router (an LLM picks from a fixed set of labels), parallel (fan-out/join through LangGraph `Send`), human_approval (`interrupt`), input/output. The frontend palette is generated from `GET /workflow-node-types`, which serves the JSON Schemas, so the frontend and backend cannot drift apart.
- **Compiler:** spec → `StateGraph` with a typed shared state (`vars`, `messages`, `node_outputs`). Each node is wrapped to emit `node.started/completed/failed` events (carrying node_id, duration and redacted I/O) and to write a `node_runs` row.
- **Live view:** the canvas subscribes to the run's SSE stream and colours nodes by status and highlights the path taken. Runs can be paused (cancel at the next node boundary while the checkpoint stays resumable), resumed or cancelled.

## 5. Multi-agent and MCP strategy
- **Multi-agent** is built on the workflow engine, not as a separate system. A "Team" is a constrained WorkflowSpec template: supervisor (a router LLM with a `delegate(agent, task)` tool limited to listed members), sequential, parallel with aggregate, or debate/review. Hard limits: `max_depth` (default 2, capped globally), a global step budget, a time budget, and no delegation to oneself or an agent higher up the chain (checked against an ancestor set). Each agent runs as a child run (`parent_run_id`). Events carry `agent_id`, `node_id` and a `delegation_reason` (a short line the supervisor states openly as a tool argument, never hidden chain-of-thought). Context between agents is isolated by default; shared context has to be enabled per edge.
- **MCP** uses the official Python `mcp` SDK (client side). Transports: **stdio** and **Streamable HTTP**; legacy SSE is accepted for older servers. `McpManager` (in the worker) keeps one pooled session per server, with timeouts, restart/backoff and a health status. Discovered tools are imported as **disabled** by default. An admin enables each tool, and each agent must be granted tools explicitly. Every MCP call goes through the same `ToolNode` checks (permission → limit → JSON-schema validation of the args → timeout → result size cap → redaction) plus approval policies. Result content is marked as untrusted. **Stdio servers run arbitrary binaries.** Registering one is limited to org admins, the command must be on an allow-list from settings (`MCP_STDIO_ALLOWED_COMMANDS`), the environment is minimal, and when deployed the server runs inside the worker container with no host mounts. This is the main security risk in V2 and is disabled by default.

## 6. Memory and knowledge architecture
- **Ingestion:** upload → `documents` row (sha256 dedupe, MIME sniffing, size cap) → extract text (`pypdf` for PDF; txt/md natively) → split into chunks of about 800 tokens with overlap → embed through the provider registry (`embeddings` capability; Ollama `nomic-embed-text` by default, chosen per collection and pinned, because changing the model means re-indexing) → `chunks`. Ingestion runs as a worker job and its status is shown in the UI. Deleting a document cascades to its chunks.
- **Retrieval:** a `knowledge_search` tool and a workflow node. Steps: vector top-k plus full-text top-k → RRF → optional reranker → metadata filters → results with citations `{doc, chunk, page}`. Retrieved text is wrapped in a delimited "untrusted content" block, and the system prompt tells the model never to follow instructions inside it.
- **Memory:** conversation memory (what exists today); session memory (a summary buffer kept per conversation); user memory and agent memory (`memories` table, written only through an explicit `remember` tool or a workflow node, searched semantically, with a list and delete UI). Ownership is enforced on every query. Agents never share memory unless the user links a shared collection to them.

## 7. Auth, authorization, tenant isolation
JWT middleware → `CurrentPrincipal(user, org, workspace, role)` dependency → service methods take the principal and filter by `workspace_id`; role checks happen in a `require(role)` helper. Settings and the MCP stdio feature are admin only. Rate limiting is an in-process token bucket per principal (enough for one API instance; can move to a Postgres-backed limiter later). Audit log entries are written for authentication, credential changes, approvals, publishing, and MCP registration. The frontend hides actions the user's role can't perform, but the backend always enforces the rule.

## 8. UI/UX redesign
- **Foundation:** keep Tailwind v4 and the tokens; add **Radix UI primitives** (accessible dialog, popover, tooltip, dropdown, tabs, toast, scroll-area), **cmdk** (command palette), **@xyflow/react** (workflow canvas), **shiki** (syntax highlighting, loaded lazily), **react-markdown + remark-gfm** to replace the hand-written renderer (tables and GFM; no raw HTML allowed), **@dagrejs/dagre** (auto-layout). Expand the token set: status colours success/warn/danger/info, elevation, radius and motion scale, a class-based theme toggle (system/light/dark, persisted).
- **Shell:** collapsible sidebar grouped as **Build** (Agents, Workflows, Teams, Skills, Tools & MCP, Knowledge) · **Run** (Conversations, Runs, Approvals with a badge) · **Admin** (Providers, Analytics, Settings/Members). Plus an Overview page, ⌘K palette, workspace switcher, user menu, notifications, and a right-hand inspector panel used by the editors. Agent Builder lives inside Agents rather than as a separate nav item.
- **Main screens:**
  - **Overview:** real counts and runs from a `/metrics` endpoint, with an explicit message when data is unavailable.
  - **Agent Builder:** tabbed sections (Basics, Model, Instructions, Skills, Tools, Knowledge, Memory, Limits & Approvals, Versions) with a test-playground side panel that runs the *draft* version, and draft/publish/diff/rollback.
  - **Workflow editor:** palette, canvas, minimap, inspector, run bar, log drawer.
  - **Chat:** streaming, GFM, code copy, tool chips, inline approval cards, timeline drawer.
  - **Runs:** filters, a timeline tree for child runs, tokens and duration, export.
  - **Approvals inbox.**
  - **Providers:** connections, test button, model table with capability badges.
  - **Tools & MCP:** servers, health, tool schemas, enable toggles.
- **UX:** skeletons on every list, toasts, confirmations for destructive actions, keyboard shortcuts, visible focus rings, `axe` checks in tests.

## 9. SDK boundary
Use npm workspaces: `packages/agent-ui` (built with Vite library mode, emitting ESM and `.d.ts`). It contains only prop-driven components: AgentChat, AgentRunTimeline, ModelSelector, ToolPicker, SkillSelector, KnowledgeSelector, ApprovalDialog, AgentExecutionStatus, AgentBuilder, WorkflowEditor. It also includes `@agent-ui/core` types (event union, specs) and a theme of CSS variables. The SDK has **no fetching**; an optional `AgentClient` adapter interface lets hosts plug in transport. The Studio consumes the package from day one of Phase 8; until then the existing `components/` rule ("no fetching") keeps the boundary clean. Packaging comes last.

---

## 10. Roadmap (dependency-aware)
Each phase: plan → implement → tests green (pytest, ruff, mypy, vitest, tsc, lint, build) → docs updated → your approval → commit. Complexity: S/M/L/XL.

| # | Phase | Depends on | Size | Main risks | Acceptance criteria (summary) |
|---|---|---|---|---|---|
| 0 | **Scope and docs:** V2 docs (`V2_ARCHITECTURE.md`, `MVP_BASELINE.md`, update SPEC/ROADMAP/CLAUDE.md to lift the postponements), CI (GitHub Actions: backend with a Postgres service, frontend) | – | S | – | Docs merged; CI green on the current code; baseline test counts recorded |
| 1 | **Design system and shell:** tokens, theme toggle, Radix primitives, sidebar/⌘K/toasts, existing pages moved into the new shell | 0 | M | Visual regressions | All existing journeys work in the new shell; axe passes; light and dark both checked; tests for each new primitive |
| 2 | **Durable runtime and tenancy foundation:** worker plus Postgres queue, checkpointer, SSE resume, events written in batches; users/orgs/workspaces, JWT, API keys, scoping, audit | 0 | **XL** | Migrating live data; regressions in run behaviour | Runs survive an API restart; reconnect resumes from `Last-Event-ID`; closing the tab doesn't cancel; cross-tenant negative tests; the MVP runs API stays compatible |
| 3 | **Multi-provider:** connections, encrypted secrets, adapters (OpenAI, Anthropic, Gemini, OpenAI-compatible), discovery, capabilities, health/test; Providers UI | 2 | L | Differences in SDK behaviour | Contract tests per adapter with recorded responses; secrets never in responses (test); Ollama unchanged |
| 4 | **Agent platform:** versions, draft/publish/diff/rollback, templates, duplicate, import/export, playground; skills v2 (versions, tags, search, import/export) | 2, 3 | L | Snapshot semantics | Runs are pinned to a version; rollback works; round-trip import/export test |
| 5 | **Tools and MCP:** capability registry with namespaced refs, MCP stdio and HTTP, discovery, enable/disable, health, custom HTTP tools (host allow-list), MCP UI | 2, 4 | L | Security of stdio servers | A test MCP server (in-repo, stdio and HTTP) is discovered and called; denied-by-default tests; timeout/size-cap tests |
| 6 | **Human approval:** policies, `interrupt` pause/resume, inbox, expiry, edit args within the schema, audit | 2, 5 | M | Resume edge cases | The model can't bypass a policy (test); approve/reject/expire/edit lifecycle tests; a pending approval survives a restart |
| 7 | **Knowledge and memory:** pgvector, ingestion jobs, hybrid search plus RRF, citations, collections UI, memory scopes and deletion | 2, 3 | L | Embedding speed on this CPU | Retrieval tests against a fixed corpus (deterministic fake embedder); isolation tests; deletion cascades |
| 8 | **Visual workflows:** spec, node registry, validator, compiler, `node_runs`, React Flow editor (drag-and-drop, undo/redo, copy/paste, auto-layout, minimap, templates, versions, import/export), live execution view | 4, 5, 6, 7 | **XL** | Editor complexity; spec drift | Server rejects invalid specs (negative tests); end-to-end: a workflow built in the UI runs and the canvas shows the path taken; Playwright drag-and-drop journey |
| 9 | **Multi-agent teams:** supervisor/sequential/parallel templates on the workflow engine, delegation limits, child runs, trace UI | 8 | L | Runaway loops | Depth/budget/cycle negative tests; trace shows who did what and why |
| 10 | **Analytics and observability:** usage/cost/latency metrics from `runs`/`node_runs`, dashboard, OpenTelemetry traces (optional Langfuse exporter), structured JSON logs | 2+ | M | – | Dashboard shows only real data; traces exported in a test with an in-memory exporter |
| 11 | **SDK packaging:** `packages/agent-ui`, docs, example host app | 1, 8 | M | Coupling | The Studio builds against the package; the example app renders AgentChat against the API |
| 12 | **Production hardening:** rate limits, proxy trust config, security review, performance pass, compose profiles, deployment docs | all | M | – | Security checklist passes; load smoke test |

**New dependencies (each justified in its own phase):** backend: `langgraph-checkpoint-postgres`, `mcp`, `langchain-openai`, `langchain-anthropic`, `langchain-google-genai`, `pgvector`, `pypdf`, `argon2-cffi`, `pyjwt`, `cryptography`, `opentelemetry-*`. Frontend: `@radix-ui/*`, `cmdk`, `@xyflow/react`, `@dagrejs/dagre`, `react-markdown`, `remark-gfm`, `shiki`, `@playwright/test`, `vitest-axe`. Infra: Postgres image becomes `pgvector/pgvector:pg17`. Node engines will be checked before each addition (engine-strict).

## Decisions confirmed
- Foundation first: Phase 2 (durable runtime and tenancy) comes before the feature phases.
- Built-in authentication: JWT access and refresh tokens plus API keys; no external identity provider.
- Local only: cloud adapters are verified with recorded responses (contract tests). Ollama (`qwen3:4b`, `nomic-embed-text`) is the manual-test path.
- First step after approval: Phase 0 only (docs and CI), then stop for review.

## 11. Verification (applies to every phase)
- `cd backend && uv run pytest && uv run ruff check . && uv run mypy app`
- `cd frontend && npm run test && npm run typecheck && npm run lint && npm run build`
- `uv run alembic upgrade head` on an empty database, plus a downgrade test
- `docker compose up -d --build`, then walk through the phase's manual journey at http://127.0.0.1:3000
- Playwright end-to-end journeys from Phase 8 onwards; fake chat model and fake embedder only, never live model calls in CI.
