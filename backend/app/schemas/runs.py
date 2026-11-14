import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    agent_id: uuid.UUID
    status: str
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
