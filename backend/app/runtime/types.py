"""Immutable runtime inputs and outputs."""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ConfigDict, Field


class SkillContent(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    name: str
    content_md: str


class ToolGrant(BaseModel):
    """A tool the agent is permitted to use, with its (already validated) config."""

    model_config = ConfigDict(frozen=True)

    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    # Calls are held for human approval (per-agent flag or a workspace policy).
    requires_approval: bool = False


class AgentConfig(BaseModel):
    """Snapshot of an agent's configuration at run start (also stored in runs.agent_snapshot)."""

    model_config = ConfigDict(frozen=True)

    agent_id: uuid.UUID
    name: str
    provider: str
    connection_id: uuid.UUID | None = None  # None = built-in provider named `provider`
    model: str
    model_params: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str = ""
    skills: list[SkillContent] = Field(default_factory=list)
    tools: list[ToolGrant] = Field(default_factory=list)
    max_tool_calls: int = 8
    run_timeout_s: int = 120


@dataclass(frozen=True)
class RuntimeCaps:
    """Global hard limits (from settings). Agent values are clamped to these."""

    max_tool_calls: int
    run_timeout_s: float
    tool_timeout_s: float


@dataclass(frozen=True)
class ResumeDecisions:
    """Human decisions for tool calls a previous run paused on."""

    approved: dict[str, dict[str, Any]] = field(default_factory=dict)  # call_id -> args
    rejected: dict[str, str] = field(default_factory=dict)  # call_id -> reason


@dataclass(frozen=True)
class RunRequest:
    run_id: uuid.UUID
    config: AgentConfig
    history: list[BaseMessage]  # prior conversation + the new user message
    conversation_id: uuid.UUID | None = None
    user_message_id: uuid.UUID | None = None
    resume: ResumeDecisions | None = None  # continuation of a run that awaited approval


RunStatus = Literal[
    "running", "completed", "failed", "cancelled", "limit_exceeded", "timeout", "waiting_approval"
]


@dataclass
class RunResult:
    status: RunStatus = "running"
    tool_call_count: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    new_messages: list[BaseMessage] = field(default_factory=list)
    # Tool calls held for approval: {"call_id", "tool", "args"}.
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
