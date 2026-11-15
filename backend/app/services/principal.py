"""The authenticated caller, resolved once per request and passed to every service call."""

import uuid
from dataclasses import dataclass
from typing import Literal

from app.db.models import ROLES
from app.services.errors import ForbiddenError

Role = Literal["viewer", "editor", "admin", "owner"]


def role_rank(role: str) -> int:
    return ROLES.index(role) if role in ROLES else -1


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    org_id: uuid.UUID
    workspace_id: uuid.UUID
    role: str
    via: Literal["token", "api_key"] = "token"

    def has(self, required: Role) -> bool:
        return role_rank(self.role) >= role_rank(required)

    def require(self, required: Role) -> None:
        if not self.has(required):
            raise ForbiddenError(f"This action requires the '{required}' role")
