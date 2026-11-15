import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RoleName = Literal["viewer", "editor", "admin", "owner"]
# Pragmatic email shape check (deliverability is not verified in V2).
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=10, max_length=256)
    name: str = Field(default="", max_length=100)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (OAuth token type, not a secret)
    expires_at: datetime


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    slug: str


class OrgMembershipRead(BaseModel):
    id: uuid.UUID
    name: str
    role: RoleName
    workspaces: list[WorkspaceRead]


class MeResponse(BaseModel):
    user: UserRead
    organizations: list[OrgMembershipRead]
    # The workspace this request resolved to (X-Workspace-Id or the default).
    current_workspace_id: uuid.UUID
    role: RoleName


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)


class MemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: RoleName
    joined_at: datetime


class MemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    role: RoleName = "editor"


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: RoleName


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    role: Literal["viewer", "editor", "admin"] = "editor"
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    role: RoleName
    user_id: uuid.UUID
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyRead):
    # Shown exactly once.
    token: str


class AuditEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    meta: dict[str, Any]
    created_at: datetime
