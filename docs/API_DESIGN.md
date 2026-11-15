# API Design

Base path: `/api`. JSON over HTTP except the run stream (SSE). Request/response bodies are Pydantic models in `backend/app/schemas/`, mirrored by TypeScript types in `frontend/src/api/types.ts`.

**Authentication (V2):** every endpoint except `GET /health` and `/auth/register|login|refresh|logout` requires `Authorization: Bearer <token>`, where the token is either a short-lived access JWT (from login/register/refresh) or an API key (`eaa_<prefix>_<secret>`). Requests act on one **workspace**: `X-Workspace-Id` selects it for user tokens (default: the user's first workspace); API keys are bound to their workspace and ignore the header. Resources of other workspaces answer **404** (no existence leak); a workspace the caller is not a member of answers **403**. Roles per organization: `viewer` (read) < `editor` (create/update/delete agents, skills, conversations; send messages; cancel runs; own API keys) < `admin` (members, workspaces, all keys, audit log) < `owner`.

## 1. Conventions

- IDs are UUIDs; timestamps are ISO 8601 UTC.
- List endpoints return arrays (pagination can be added later with `limit`/`cursor` query params).
- `PUT` replaces the full resource (including nested `skill_ids` and `tools` for agents).
- Errors use problem JSON: `{"type": "...", "title": "...", "detail": "...", "status": 422}`.

| Status | Meaning |
|---|---|
| 400 | Malformed request |
| 401 | Missing/invalid/expired credentials (`WWW-Authenticate: Bearer`) |
| 403 | Role too low, or a workspace the caller is not a member of |
| 404 | Resource not found (also: belongs to another workspace) |
| 429 | Too many login/registration attempts |
| 409 | Conflict (duplicate skill slug; tools enabled on a model without tool support) |
| 422 | Validation error (unknown tool, invalid tool config, limits above global caps) |
| 502 | Provider (Ollama) unreachable |

## 2. Responsibilities by layer

- **Router:** parse path/query/body, call one service method, return a response schema. No business logic.
- **Service:** validation that needs other data (tool names against the registry, tool config against the tool's `Config`, skill IDs exist, limits ≤ global caps, model tool capability), transactions, orchestration.
- **Schema:** field-level validation (lengths, ranges, enums).

## 3. Endpoints

### Auth & organization
| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | `{email, password (≥10), name}` → 201 `{access_token, token_type, expires_at}` + httpOnly `eaa_refresh` cookie (SameSite=Strict, Path=/api/auth). The first user owns the Default organization (pre-existing data); later users get their own organization + "Personal" workspace. 403 if registration is disabled, 409 duplicate email |
| POST | `/auth/login` | `{email, password}` → token + cookie; uniform 401 for unknown email/wrong password; rate limited (429) |
| POST | `/auth/refresh` | Rotates the refresh cookie and returns a new access token. Reusing a rotated token revokes the whole session family (401) |
| POST | `/auth/logout` | Revokes the refresh token family; 204 |
| GET | `/auth/me` | `{user, organizations[{id, name, role, workspaces[]}], current_workspace_id, role}` |
| GET/POST | `/workspaces` | List the organization's workspaces / create one (admin; seeds built-in skills) |
| GET/POST | `/members` | List / add an existing user by email with a role (admin; cannot grant above own role) |
| PATCH/DELETE | `/members/{user_id}` | Change role / remove (admin; never the last owner; never someone with a higher role) |
| GET/POST | `/api-keys` | List (own; admins: all) / create `{name, role ≤ own, expires_in_days?}` → token shown once (editor; API keys cannot create keys) |
| DELETE | `/api-keys/{id}` | Revoke (own key, or admin) |
| GET | `/audit?limit=&before=` | Organization audit log, newest first (admin) |

### Health
| Method | Path | Response |
|---|---|---|
| GET | `/health` | `{status, database: ok\|error, ollama: ok\|error}` |

### Agents
| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/agents` | — | `AgentSummary[]` (id, name, description, provider, model, updated_at) |
| POST | `/agents` | `AgentWrite` | `Agent` (201) |
| GET | `/agents/{id}` | — | `Agent` |
| PUT | `/agents/{id}` | `AgentWrite` | `Agent` |
| DELETE | `/agents/{id}` | — | 204 (cascades conversations/runs) |

`AgentWrite`:
```json
{
  "name": "Math helper",
  "description": "Answers arithmetic questions",
  "provider": "ollama",
  "model": "qwen3:4b",
  "model_params": {"temperature": 0.2, "num_ctx": 8192, "think": false},
  "system_prompt": "You are a precise assistant.",
  "skill_ids": ["<uuid>"],
  "tools": [
    {"name": "calculator", "config": {}},
    {"name": "file_reader", "config": {"subdir": "notes"}}
  ],
  "max_tool_calls": 8,
  "run_timeout_s": 120
}
```
Save-time checks: unknown tool / invalid tool config / unknown provider / limits above caps → 422. If the agent has tools and the provider reports the model **lacks** tool support → 409. If capability is unknown (provider offline, model not pulled yet) the save is allowed; the run pre-flight check enforces it.

`Agent` = `AgentWrite` fields (with `skills` expanded to `{id, slug, name}` in order) + `id`, `created_at`, `updated_at`.

### Skills
| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/skills` | — | `Skill[]` (without `content_md`) |
| POST | `/skills` | `SkillWrite` `{slug, name, description, content_md}` | `Skill` (201) |
| GET | `/skills/{id}` | — | `Skill` (with `content_md`) |
| PUT | `/skills/{id}` | `SkillWrite` | `Skill` |
| DELETE | `/skills/{id}` | — | 204 (detaches from agents) |

### Tools
| Method | Path | Response |
|---|---|---|
| GET | `/tools` | `ToolInfo[]`: `{name, description, args_schema, config_schema, timeout_s}` (JSON Schemas) |

### Providers (V2)

`{provider}` is a built-in name (`ollama`) or a connection id. Secrets are write-only (encrypted with `SECRET_ENCRYPTION_KEY`); responses expose `has_secret` and `secret_hint` (last 4 chars) only.

| Method | Path | Notes |
|---|---|---|
| GET | `/providers` | Built-ins + workspace connections: `{name, id, label, kind, builtin, base_url, has_secret, secret_hint, available, status, last_error, last_checked_at}` |
| POST | `/providers` | Create a connection `{name, kind: openai|anthropic|gemini|openai_compatible|ollama, base_url?, api_key?}` (admin). Base URLs: http(s) only, no link-local/metadata hosts, no credentials in the URL |
| PATCH/DELETE | `/providers/{id}` | Update (omit `api_key` to keep it, `""` removes it) / delete (409 while agents use it) (admin) |
| POST | `/providers/{provider}/test` | Health check (lists models); records status |
| GET | `/providers/{provider}/models` | `{name, size, supports_tools (true|false|null), supports_thinking, tools_source (provider|probe|user|null), context_window, display_name}` — capabilities are only those the provider states, plus probe/user overrides where it states nothing |
| PUT | `/providers/{provider}/models/{model}/capabilities` | `{supports_tools: bool|null}` override (editor) |
| POST | `/providers/{provider}/models/{model}/probe` | Live tool-calling check (one small request) → `{model, supports_tools, detail}`; records the result (editor) |

Agents reference a connection with `connection_id` (null = built-in `provider`); `model_params` accepts `temperature`, `top_p`, `max_tokens` for every provider and `num_ctx`/`think` for Ollama only (422 otherwise). A tool-enabled agent on a model with unknown tool support can be saved but its runs fail with `model_no_tool_support` until the support is confirmed.

### Providers (MVP endpoints, unchanged paths)
| Method | Path | Response |
|---|---|---|
| GET | `/providers` | `[{name: "ollama", available: bool}]` |
| GET | `/providers/{provider}/models` | `[{name, size, supports_tools, supports_thinking}]` from Ollama `/api/tags` + `/api/show` |

### Conversations
| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/conversations?agent_id=` | — | `ConversationSummary[]` |
| POST | `/conversations` | `{agent_id, title?}` | `Conversation` (201) |
| GET | `/conversations/{id}` | — | `Conversation` with `messages[]` (ordered by `seq`) and `runs[]` (ordered by start) |
| DELETE | `/conversations/{id}` | — | 204 |
| POST | `/conversations/{id}/messages` | `{content}` | **SSE stream** (§4) |

The POST-messages endpoint persists the user message, creates a run and streams its events. Errors before the stream starts return normal HTTP errors: 404 unknown conversation, 422 invalid body, **409 if a run is already active in this conversation**. Errors after the stream starts are delivered as `run.failed`. The first message sets the conversation title (first line, max 60 chars) if it still has the default title. The run is queued and executed by a run worker; **closing the connection does not cancel it** (V2 change — use `POST /runs/{id}/cancel`); reattach with `GET /runs/{id}/stream`.

### Runs
| Method | Path | Response |
|---|---|---|
| GET | `/runs/{id}` | `Run`: `{id, conversation_id, agent_id, status, tool_call_count, usage, error, started_at, finished_at}` |
| GET | `/runs/{id}/events` | Persisted `RunEvent[]` (timeline replay; no token deltas) |
| GET | `/runs/{id}/stream` | SSE: replays persisted events with `seq` > `Last-Event-ID` header (or `?after=`), then streams live events (including token deltas) until the terminal event. Works for active and finished runs. 404 if unknown |
| POST | `/runs/{id}/cancel` | 202; a queued run is cancelled immediately, a running one is stopped by its worker; the run ends with `run.cancelled`. 409 if the run is not active, 404 if unknown |

Run `status` values: `queued` (waiting for a worker), `running`, `completed`, `failed`, `cancelled`, `limit_exceeded`, `timeout`.

## 4. Streaming event protocol (SSE)

Response `Content-Type: text/event-stream`. Each frame:
```
id: <seq>
event: <type>
data: {"run_id": "...", "seq": 3, "ts": "2026-11-14T10:00:00Z", ...payload}
```
A keep-alive comment (`: ping`) is sent every 15 s. `seq` is monotonically increasing per run. Every stream ends with **exactly one** terminal event (`run.completed`, `run.failed` or `run.cancelled`).

| Type | Payload | Persisted |
|---|---|---|
| `run.started` | `agent_id, model, conversation_id, user_message_id` | yes |
| `reasoning.delta` | `text` (thinking models only) | no |
| `message.delta` | `text` | no |
| `message.completed` | `message_id, content` | yes |
| `tool.call.started` | `call_id, tool, args` | yes |
| `tool.call.completed` | `call_id, tool, result` (truncated preview), `duration_ms` | yes |
| `tool.call.failed` | `call_id, tool, error, kind` (`validation`/`permission`/`timeout`/`execution`) | yes |
| `run.completed` | `status, tool_call_count, usage, duration_ms` | yes |
| `run.failed` | `code` (`limit_exceeded`/`timeout`/`provider_error`/`model_no_tool_support`/`internal_error`), `message` | yes |
| `run.cancelled` | — | yes |

**Terminal event ↔ `runs.status` mapping:**

| `runs.status` | Terminal event |
|---|---|
| `completed` | `run.completed` (`status: "completed"`) |
| `limit_exceeded` | `run.failed` (`code: "limit_exceeded"`) |
| `timeout` | `run.failed` (`code: "timeout"`) |
| `failed` | `run.failed` (`code: "provider_error"`, `"model_no_tool_support"` or `"internal_error"`) |
| `cancelled` | `run.cancelled` |

Every tool call emits `tool.call.started` followed by exactly one `tool.call.completed` or `tool.call.failed` with the same `call_id`. A tool call refused because `max_tool_calls` is reached emits no tool event; the run ends with `run.failed` (`limit_exceeded`).

Error messages in events are user-safe; stack traces are logged server-side only.

The frontend consumes the stream with `fetch` + `ReadableStream` and a small SSE parser (browser `EventSource` cannot send POST bodies), reducing events into chat and timeline state.
