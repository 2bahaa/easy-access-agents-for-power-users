import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderKindName = Literal["ollama", "openai", "openai_compatible", "anthropic", "gemini"]


class ProviderRead(BaseModel):
    """A provider an agent can use: the built-in Ollama or a workspace connection."""

    # Built-ins keep their registry name (e.g. "ollama"); connections use their UUID.
    name: str
    id: uuid.UUID | None = None
    label: str
    kind: ProviderKindName
    builtin: bool
    base_url: str | None = None
    has_secret: bool = False
    secret_hint: str | None = None
    available: bool | None = None  # live check for built-ins; last test result otherwise
    status: Literal["ok", "error", "unknown"] = "unknown"
    last_error: str | None = None
    last_checked_at: datetime | None = None


class ProviderConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    kind: ProviderKindName
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)


class ProviderConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, max_length=500)
    # Omit to keep the stored key; empty string removes it.
    api_key: str | None = Field(default=None, max_length=4096)


class ModelRead(BaseModel):
    name: str
    size: int | None
    # Effective capability: provider-reported, else probe/user override, else None (unknown).
    supports_tools: bool | None
    supports_thinking: bool | None
    tools_source: Literal["provider", "probe", "user"] | None = None
    context_window: int | None = None
    display_name: str | None = None


class CapabilityOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None removes the override.
    supports_tools: bool | None


class ProbeResult(BaseModel):
    model: str
    supports_tools: bool
    detail: str
