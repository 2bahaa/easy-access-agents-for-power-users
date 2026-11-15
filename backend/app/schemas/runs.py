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
