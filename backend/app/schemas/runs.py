import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str = "agent"
    conversation_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    workflow_id: uuid.UUID | None = None
    inputs: dict[str, Any] | None = None
    output: str | None = None
    status: str
    agent_version: int | None = None  # None = ran the draft
    resume_of: uuid.UUID | None = None  # continuation of a run that awaited approval
    tool_call_count: int
    usage: dict[str, Any]
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class RunEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class RunListItem(RunRead):
    agent_name: str | None = None
    workflow_name: str | None = None


class RunPage(BaseModel):
    items: list[RunListItem]
    total: int


class DailyUsage(BaseModel):
    date: str
    runs: int
    failed: int
    tokens: int


class AgentUsage(BaseModel):
    agent_id: uuid.UUID
    name: str
    runs: int
    failed: int


class ToolUsage(BaseModel):
    tool: str
    calls: int
    failed: int


class AnalyticsSummary(BaseModel):
    days: int
    runs: int
    by_status: dict[str, int]
    by_kind: dict[str, int]
    success_rate: float | None  # completed / (completed + failed); None without data
    tool_calls: int
    input_tokens: int
    output_tokens: int
    runs_without_usage: int  # runs whose provider reported no token usage
    avg_duration_ms: int | None
    p95_duration_ms: int | None
    daily: list[DailyUsage]
    top_agents: list[AgentUsage]
    top_tools: list[ToolUsage]
