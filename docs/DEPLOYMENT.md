# Deployment & security checklist

Easy Access Agents ships as four containers: PostgreSQL (`pgvector/pgvector:pg17` recommended), the API (FastAPI; applies migrations on start), one or more run workers (`python -m app.worker`) and the Studio (nginx serving the SPA and proxying `/api`). Ollama runs wherever you host models.

## Minimum production configuration
Set `ENVIRONMENT=production`. The API **refuses to start** if any of these is unsafe (`Settings.production_problems`):

| Variable | Requirement |
|---|---|
| `JWT_SECRET` | Random, ≥ 32 characters, identical on every API process (`python -c "import secrets;print(secrets.token_urlsafe(48))"`) |
| `SECRET_ENCRYPTION_KEY` | Fernet key for stored provider/MCP credentials (`python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`). Rotate by prepending a new key: `new,old` |
| `COOKIE_SECURE` | `true`: serve over HTTPS (terminate TLS at your load balancer or in front of nginx) |
| `CORS_ORIGINS` | Explicit origins; never `*` |
| `DATABASE_URL` / `POSTGRES_PASSWORD` | Not the example `change-me` |

Also review:
- `FORWARDED_ALLOW_IPS`: only your reverse proxy's addresses or CIDRs. Client IPs drive the login limiter, so never use `*` when the API port is reachable directly. Compose defaults to the private Docker ranges.
- `ALLOW_REGISTRATION=false` once your organization exists; invite members instead.
- `MCP_STDIO_ALLOWED_COMMANDS`: keep empty unless needed. Stdio MCP servers are local processes.
- `CUSTOM_TOOL_ALLOWED_HOSTS` and `PROVIDER_BLOCKED_HOSTS`: outbound allow-list and SSRF guard.
- Limits: `MAX_TOOL_CALLS_CAP`, `RUN_TIMEOUT_CAP_S`, `TOOL_TIMEOUT_S`, `WORKFLOW_TIMEOUT_S`, `MAX_REQUEST_BYTES` (1 MB), `KNOWLEDGE_MAX_UPLOAD_BYTES` (10 MB), `RUNS_PER_MINUTE` (30 per user), `LOGIN_ATTEMPTS_PER_5MIN`.

## Scaling
- The API holds no run state. Run several API replicas (`API_WORKERS` or more containers) and several workers. Workers claim runs with `SKIP LOCKED`, heartbeat them, and reap runs whose worker died.
- Set `RUN_WORKER_EMBEDDED=false` on API replicas when dedicated workers run.
- Rate limiters are per process: effective limits scale with the replica count. Put an edge rate limiter (load balancer or WAF) in front for strict global limits.

## Observability
- `LOG_FORMAT=json` gives one JSON object per line, with `run_id` and `trace_id` when available.
- `OTEL_ENABLED=true` with `OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318` exports traces (`run.agent`, `run.workflow`, `tool.call`) to any OTLP backend.
- `GET /api/health` reports the database and Ollama (used by the compose health checks). Usage and reliability: Studio → Runs, or `GET /api/analytics/summary`.

## Backups & migrations
- All state is in PostgreSQL. Back it up with `pg_dump` or your platform's snapshots. Uploaded knowledge text and embeddings live in the database; the file-reader sandbox (`WORKSPACE_DIR`) is a volume.
- Migrations run on API start (`alembic upgrade head`). They are additive and expand-only; take a backup before upgrading.

## Security checklist (reviewed in Phase 12)
- [x] Authentication on every endpoint except health, login, registration and refresh; argon2 passwords; short-lived JWTs; rotating refresh cookie (HttpOnly, SameSite=Strict, Secure in production); hashed `eaa_` API keys.
- [x] Tenant isolation in the service layer (every query filtered by workspace; cross-tenant access returns 404; negative tests). Roles enforced in services, not only in the UI.
- [x] Audit log for authentication, members, API keys, credentials, publishing, MCP registration and approval decisions.
- [x] Secrets encrypted at rest (Fernet) and never returned (only `has_secret` and the last 4 characters).
- [x] Tool execution checks permission, call limits, Pydantic/JSON-Schema arguments and timeouts. No eval/exec; the file reader is sandboxed (traversal, symlink, binary and size checks); custom HTTP tools use a host allow-list; SSRF guard on provider URLs; MCP stdio limited to allow-listed commands.
- [x] Human approval enforced by the backend (policies and per-tool flags); decisions are audited; requests expire.
- [x] The workflow condition language is a whitelisted AST (sandbox negative tests). Specs are validated server-side; the canvas JSON is never trusted.
- [x] Retrieved knowledge and tool results are delimited as untrusted content.
- [x] Request size limits (API and nginx), per-user run rate limit, login and registration limiters.
- [x] Security headers: nosniff, `X-Frame-Options: DENY`, `Referrer-Policy`, and a CSP on the Studio with no inline scripts.
- [x] Only trusted proxies may set the forwarded client IP.
- [x] Model reasoning is shown only when the provider returns it as a separate field and the user opens it; team delegations show an explicit, model-stated reason, not hidden chain-of-thought.
- [ ] Organization-specific items: TLS certificates, backups, an edge rate limiter or WAF, secret management (Vault or a cloud KMS) instead of `.env`.
