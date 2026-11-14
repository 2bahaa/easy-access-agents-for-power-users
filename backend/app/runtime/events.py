"""Streaming event protocol (docs/API_DESIGN.md §4).

One Pydantic discriminated union, mirrored by a TypeScript union in the frontend.
Change both together.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field, TypeAdapter


def _now() -> datetime:
    return datetime.now(UTC)


class _EventBase(BaseModel):
    persisted: ClassVar[bool] = True  # stored in run_events (token deltas are not)

    run_id: uuid.UUID
    seq: int
    ts: datetime = Field(default_factory=_now)


class RunStarted(_EventBase):
    type: Literal["run.started"] = "run.started"
    agent_id: uuid.UUID
    model: str
    conversation_id: uuid.UUID | None = None
    user_message_id: uuid.UUID | None = None


class ReasoningDelta(_EventBase):
    persisted: ClassVar[bool] = False
    type: Literal["reasoning.delta"] = "reasoning.delta"
    text: str


class MessageDelta(_EventBase):
    persisted: ClassVar[bool] = False
    type: Literal["message.delta"] = "message.delta"
    text: str


class MessageCompleted(_EventBase):
    type: Literal["message.completed"] = "message.completed"
    message_id: str
    content: str


class ToolCallStarted(_EventBase):
    type: Literal["tool.call.started"] = "tool.call.started"
    call_id: str
    tool: str
    args: dict[str, Any]


class ToolCallCompleted(_EventBase):
    type: Literal["tool.call.completed"] = "tool.call.completed"
    call_id: str
    tool: str
    result: str  # preview, truncated
    duration_ms: int


ToolFailureKind = Literal["validation", "permission", "timeout", "execution"]


class ToolCallFailed(_EventBase):
    type: Literal["tool.call.failed"] = "tool.call.failed"
    call_id: str
    tool: str
    error: str
    kind: ToolFailureKind


class RunCompleted(_EventBase):
    type: Literal["run.completed"] = "run.completed"
    status: Literal["completed"] = "completed"
    tool_call_count: int
    usage: dict[str, int]
    duration_ms: int


RunFailureCode = Literal[
    "limit_exceeded", "timeout", "provider_error", "model_no_tool_support", "internal_error"
]


class RunFailed(_EventBase):
    type: Literal["run.failed"] = "run.failed"
    code: RunFailureCode
    message: str


class RunCancelled(_EventBase):
    type: Literal["run.cancelled"] = "run.cancelled"


AgentEvent = Annotated[
    RunStarted
    | ReasoningDelta
    | MessageDelta
    | MessageCompleted
    | ToolCallStarted
    | ToolCallCompleted
    | ToolCallFailed
    | RunCompleted
    | RunFailed
    | RunCancelled,
    Field(discriminator="type"),
]

TERMINAL_TYPES = frozenset({"run.completed", "run.failed", "run.cancelled"})

agent_event_adapter: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)
