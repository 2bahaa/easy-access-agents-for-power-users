"""Application settings, loaded from environment variables and the repo-root `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://eaa:change-me@127.0.0.1:5432/eaa"
    ollama_base_url: str = "http://127.0.0.1:11434"
    workspace_dir: Path = REPO_ROOT / "workspace"
    skills_dir: Path = BACKEND_DIR / "skills"

    # Global hard caps: agent settings may be lower, never higher.
    max_tool_calls_cap: int = Field(default=20, ge=1)
    run_timeout_cap_s: int = Field(default=300, ge=5)
    tool_timeout_s: int = Field(default=10, ge=1)

    # Durable run execution (Postgres job queue). The API process embeds a worker by default;
    # set RUN_WORKER_EMBEDDED=false and run `python -m app.worker` to execute runs separately.
    run_worker_embedded: bool = True
    run_worker_concurrency: int = Field(default=4, ge=1, le=64)
    run_heartbeat_s: float = Field(default=5.0, gt=0)
    # A running run whose worker has not sent a heartbeat for this long is marked failed.
    run_stale_after_s: float = Field(default=30.0, gt=0)
    # Fallback poll interval for queued runs (NOTIFY wakes the worker immediately).
    run_poll_interval_s: float = Field(default=2.0, gt=0)

    # Authentication. JWT_SECRET must be set (and shared by every API process) in any real
    # deployment; when empty a random per-process secret is used (tokens die on restart).
    jwt_secret: SecretStr = SecretStr("")
    access_token_ttl_s: int = Field(default=900, ge=60)
    refresh_token_ttl_days: int = Field(default=14, ge=1)
    # Anyone may register (creating their own organization). The first user always may:
    # they become the owner of the Default organization that holds pre-existing data.
    allow_registration: bool = True
    # Send the refresh cookie only over HTTPS (enable behind TLS).
    cookie_secure: bool = False
    # Brute-force protection (per API process): login attempts per (client, email) per
    # 5 minutes, registrations per client per hour.
    login_attempts_per_5min: int = Field(default=10, ge=1)
    registrations_per_hour: int = Field(default=20, ge=1)

    # Fernet key(s) for encrypting stored credentials (comma-separated; first encrypts).
    # Without it, provider connections that need an API key cannot be created.
    secret_encryption_key: SecretStr = SecretStr("")
    # Hosts that provider connections may NOT target (SSRF guard), in addition to
    # link-local/metadata addresses which are always blocked.
    provider_blocked_hosts: str = ""

    # MCP stdio servers start local processes: only these commands may be registered
    # (comma-separated executables, e.g. "npx,uvx,python", or a JSON list). Empty = disabled.
    mcp_stdio_allowed_commands: str = ""
    # Hosts custom HTTP tools may call (comma-separated; "*.example.com" wildcards).
    custom_tool_allowed_hosts: str = ""

    # Knowledge uploads larger than this are rejected.
    knowledge_max_upload_bytes: int = Field(default=10_000_000, ge=1000)

    # Upper bound for one workflow run (all nodes together).
    workflow_timeout_s: int = Field(default=600, ge=10)

    # Pending approval requests expire after this long (then count as rejected).
    approval_ttl_s: int = Field(default=86_400, ge=60)

    # Observability: LOG_FORMAT=json for structured logs; traces only when OTEL_ENABLED.
    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = ""  # e.g. http://127.0.0.1:4318; empty = console
    otel_service_name: str = "easy-access-agents"

    # ENVIRONMENT=production refuses to start with unsafe settings (see production_problems).
    environment: Literal["development", "production"] = "development"
    # Largest accepted request body (knowledge uploads use KNOWLEDGE_MAX_UPLOAD_BYTES).
    max_request_bytes: int = Field(default=1_000_000, ge=10_000)
    # Runs a user may start per minute (messages, workflow runs), per API process.
    runs_per_minute: int = Field(default=30, ge=1)

    # Comma-separated list of allowed browser origins.
    cors_origins: str = "http://localhost:5173"

    @field_validator("workspace_dir", "skills_dir")
    @classmethod
    def _resolve_relative_to_backend(cls, v: Path) -> Path:
        return v if v.is_absolute() else (BACKEND_DIR / v).resolve()

    def production_problems(self) -> list[str]:
        """Settings that are acceptable for local development but unsafe in production."""
        problems = []
        if len(self.jwt_secret.get_secret_value()) < 32:
            problems.append("JWT_SECRET must be set to a random value of at least 32 characters")
        if not self.secret_encryption_key.get_secret_value():
            problems.append("SECRET_ENCRYPTION_KEY must be set (Fernet key)")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true (serve over HTTPS)")
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS must list explicit origins, not *")
        if "change-me" in self.database_url:
            problems.append("DATABASE_URL still uses the example password")
        return problems

    @property
    def listen_dsn(self) -> str:
        """Plain asyncpg DSN (no SQLAlchemy driver suffix) for LISTEN/NOTIFY connections."""
        from sqlalchemy import make_url

        url = make_url(self.database_url).set(drivername="postgresql")
        return url.render_as_string(hide_password=False)

    @property
    def mcp_stdio_commands(self) -> list[str]:
        """Comma-separated, or a JSON list for entries containing commas
        (e.g. ["C:\Tools,v2\python.exe"])."""
        raw = self.mcp_stdio_allowed_commands.strip()
        if raw.startswith("["):
            import json

            return [str(c).strip() for c in json.loads(raw) if str(c).strip()]
        return [c.strip() for c in raw.split(",") if c.strip()]

    @property
    def custom_tool_hosts(self) -> list[str]:
        return [h.strip().lower() for h in self.custom_tool_allowed_hosts.split(",") if h.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
