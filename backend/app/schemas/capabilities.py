import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ENV_KEY = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"


class McpServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=31)
    transport: Literal["stdio", "http"]
    command: str | None = Field(default=None, max_length=500)
    args: list[str] = Field(default_factory=list, max_length=50)
    url: str | None = Field(default=None, max_length=500)
    # Write-only secrets: environment variables (stdio) / HTTP headers (http).
    env: dict[str, str] = Field(default_factory=dict, max_length=30)
    headers: dict[str, str] = Field(default_factory=dict, max_length=30)
    timeout_s: int = Field(default=30, ge=1, le=300)


class McpServerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    command: str | None = Field(default=None, max_length=500)
    args: list[str] | None = Field(default=None, max_length=50)
    url: str | None = Field(default=None, max_length=500)
    env: dict[str, str] | None = None  # replaces all env vars when given
    headers: dict[str, str] | None = None
    timeout_s: int | None = Field(default=None, ge=1, le=300)


class McpToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str
    input_schema: dict[str, Any]
    enabled: bool


class McpServerRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    transport: str
    command: str | None
    args: list[str]
    url: str | None
    secret_keys: list[str]  # names only; values are never returned
    enabled: bool
    timeout_s: int
    status: str
    last_error: str | None
    last_checked_at: datetime | None
    tools: list[McpToolRead] = Field(default_factory=list)


class RefreshResult(BaseModel):
    server: McpServerRead
    warnings: list[str]


class ToolToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class HttpParamWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,39}$")
    type: Literal["string", "number", "integer", "boolean"] = "string"
    location: Literal["query", "path", "body"] = "query"
    required: bool = True
    description: str = Field(default="", max_length=300)


class CustomToolWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,33}$")
    description: str = Field(min_length=1, max_length=1000)
    method: Literal["GET", "POST"] = "GET"
    url_template: str = Field(min_length=8, max_length=1000)
    params: list[HttpParamWrite] = Field(default_factory=list, max_length=20)
    # Write-only. Omit to keep stored headers; {} removes them.
    headers: dict[str, str] | None = None
    timeout_s: int = Field(default=15, ge=1, le=120)
    enabled: bool = True


class CustomToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    tool_name: str
    description: str
    method: str
    url_template: str
    params: list[HttpParamWrite]
    header_keys: list[str]
    timeout_s: int
    enabled: bool
    updated_at: datetime
