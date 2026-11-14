import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class SkillWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    content_md: str = Field(default="", max_length=50_000)


class SkillSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str
    is_builtin: bool
    updated_at: datetime


class SkillRead(SkillSummary):
    content_md: str
    created_at: datetime


class SkillRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
