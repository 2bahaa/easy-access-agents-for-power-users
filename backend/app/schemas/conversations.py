import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.runs import RunRead


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=200)
    # Playground conversations test the agent's draft and are hidden from the history.
    playground: bool = False


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    title: str
    kind: str = "chat"
    created_at: datetime
    updated_at: datetime


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID | None
    seq: int
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None
    tool_call_id: str | None
    tool_name: str | None
    created_at: datetime


class ConversationRead(ConversationSummary):
    messages: list[MessageRead]
    runs: list[RunRead]


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)
