"""Application settings, loaded from environment variables and the repo-root `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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

    # Comma-separated list of allowed browser origins.
    cors_origins: str = "http://localhost:5173"

    @field_validator("workspace_dir", "skills_dir")
    @classmethod
    def _resolve_relative_to_backend(cls, v: Path) -> Path:
        return v if v.is_absolute() else (BACKEND_DIR / v).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
