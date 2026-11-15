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
    agent_id: uuid.UUID | None = None  # None for workflow runs
    model: str | None = None
    workflow_id: uuid.UUID | None = None
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


class ApprovalRequested(_EventBase):
    """A tool call was held for human approval (it has not been executed)."""

    type: Literal["approval.requested"] = "approval.requested"
    call_id: str
    tool: str
    args: dict[str, Any]


class NodeStarted(_EventBase):
    """Workflow runs: a node began executing."""

    type: Literal["node.started"] = "node.started"
    node_id: str
    node_type: str
    label: str = ""


class NodeCompleted(_EventBase):
    type: Literal["node.completed"] = "node.completed"
    node_id: str
    output: str  # preview, truncated
    duration_ms: int


class NodeFailed(_EventBase):
    type: Literal["node.failed"] = "node.failed"
    node_id: str
    error: str


class RunCompleted(_EventBase):
    type: Literal["run.completed"] = "run.completed"
    status: Literal["completed"] = "completed"
    tool_call_count: int  # workflow runs: executed nodes
    usage: dict[str, int]
    duration_ms: int
    output: str | None = None  # workflow result


RunFailureCode = Literal[
    "limit_exceeded",
    "timeout",
    "provider_error",
    "model_no_tool_support",
    "internal_error",
    "node_failed",
]


class RunFailed(_EventBase):
    type: Literal["run.failed"] = "run.failed"
    code: RunFailureCode
    message: str


class RunCancelled(_EventBase):
    type: Literal["run.cancelled"] = "run.cancelled"


class RunWaitingApproval(_EventBase):
    """Terminal for this run: it paused until humans decide the pending tool calls; a
    continuation run then executes the approved ones."""

    type: Literal["run.waiting_approval"] = "run.waiting_approval"
    pending: list[str]  # call ids


AgentEvent = Annotated[
    RunStarted
    | ReasoningDelta
    | MessageDelta
    | MessageCompleted
    | ToolCallStarted
    | ToolCallCompleted
    | ToolCallFailed
    | ApprovalRequested
    | NodeStarted
    | NodeCompleted
    | NodeFailed
    | RunCompleted
    | RunFailed
    | RunCancelled
    | RunWaitingApproval,
    Field(discriminator="type"),
]

TERMINAL_TYPES = frozenset({"run.completed", "run.failed", "run.cancelled", "run.waiting_approval"})

agent_event_adapter: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)
