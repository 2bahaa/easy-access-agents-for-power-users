import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.skills import SkillRef


class ModelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Portable parameters (every provider).
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    # Ollama only (validated against the agent's provider kind).
    num_ctx: int | None = Field(default=None, ge=256, le=1_048_576)
    think: bool | None = None


class ToolSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)


class AgentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    provider: str = Field(default="ollama", min_length=1, max_length=50)
    # A workspace provider connection; when set, `provider` is taken from its kind.
    connection_id: uuid.UUID | None = None
    model: str = Field(min_length=1, max_length=200)
    model_params: ModelParams = Field(default_factory=ModelParams)
    system_prompt: str = Field(default="", max_length=20_000)
    skill_ids: list[uuid.UUID] = Field(default_factory=list)
    tools: list[ToolSelection] = Field(default_factory=list)
    # Upper bounds are enforced against global caps in the service layer.
    max_tool_calls: int = Field(default=8, ge=1)
    run_timeout_s: int = Field(default=120, ge=5)

    @field_validator("skill_ids")
    @classmethod
    def _unique_skills(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(v)) != len(v):
            raise ValueError("skill_ids must be unique")
        return v

    @field_validator("tools")
    @classmethod
    def _unique_tools(cls, v: list[ToolSelection]) -> list[ToolSelection]:
        names = [t.name for t in v]
        if len(set(names)) != len(names):
            raise ValueError("tool names must be unique")
        return v


class AgentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    provider: str
    connection_id: uuid.UUID | None = None
    model: str
    updated_at: datetime


class AgentRead(AgentSummary):
    # Latest published version (None = never published) and whether the draft differs.
    published_version: int | None = None
    has_unpublished_changes: bool = True
    model_params: ModelParams
    system_prompt: str
    skills: list[SkillRef]
    tools: list[ToolSelection]
    max_tool_calls: int
    run_timeout_s: int
    created_at: datetime
