"""Agent versions, templates, import/export documents; skill versions/templates."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agents import ModelParams, ToolSelection
from app.schemas.skills import SLUG_PATTERN

AGENT_EXPORT_FORMAT: Literal["eaa.agent/v1"] = "eaa.agent/v1"


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(default="", max_length=500)


class AgentVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    note: str
    created_by: uuid.UUID | None
    created_at: datetime


class AgentVersionRead(AgentVersionSummary):
    write_config: dict[str, Any]


class AgentStatus(BaseModel):
    published_version: int | None
    has_unpublished_changes: bool


class DuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)


class AgentTemplate(BaseModel):
    id: str
    name: str
    description: str
    category: str
    system_prompt: str
    tools: list[ToolSelection] = Field(default_factory=list)
    model_params: ModelParams = Field(default_factory=ModelParams)
    max_tool_calls: int = 8
    run_timeout_s: int = 120
    # Built-in skills (by slug) the template suggests attaching.
    suggested_skills: list[str] = Field(default_factory=list)


class ExportedSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    content_md: str = Field(default="", max_length=50_000)
    category: str = Field(default="general", max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=10)


class ExportedAgent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    provider_kind: str = Field(default="ollama", max_length=50)
    # Name of the workspace provider connection (never its id or key); None = built-in.
    connection_name: str | None = Field(default=None, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    model_params: ModelParams = Field(default_factory=ModelParams)
    system_prompt: str = Field(default="", max_length=20_000)
    skills: list[str] = Field(default_factory=list)  # slugs, defined in `skills` below
    tools: list[ToolSelection] = Field(default_factory=list)
    max_tool_calls: int = Field(default=8, ge=1)
    run_timeout_s: int = Field(default=120, ge=5)


class AgentExportDocument(BaseModel):
    """Portable agent definition. Contains no ids, secrets or conversation data."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["eaa.agent/v1"] = AGENT_EXPORT_FORMAT
    exported_at: datetime | None = None
    agent: ExportedAgent
    skills: list[ExportedSkill] = Field(default_factory=list, max_length=50)


class ImportResult(BaseModel):
    agent_id: uuid.UUID
    created_skills: list[str]
    reused_skills: list[str]


class SkillVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    name: str
    description: str
    content_md: str
    created_by: uuid.UUID | None
    created_at: datetime


class SkillImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown: str = Field(min_length=1, max_length=60_000)
