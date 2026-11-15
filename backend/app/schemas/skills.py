import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class SkillWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    content_md: str = Field(default="", max_length=50_000)
    category: str = Field(default="general", min_length=1, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for tag in v:
            t = tag.strip().lower()
            if not re.fullmatch(r"[a-z0-9][a-z0-9 _-]{0,39}", t):
                raise ValueError("tags: 1-40 characters of letters, digits, space, - or _")
            if t not in out:
                out.append(t)
        return out


class SkillSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str
    is_builtin: bool
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    version: int = 1
    updated_at: datetime


class SkillRead(SkillSummary):
    content_md: str
    created_at: datetime


class SkillRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
