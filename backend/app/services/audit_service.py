"""Append-only audit trail of security-relevant actions.

`record` only adds the row to the session: it is committed atomically with the action it
describes (or not at all if the action fails).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.services.principal import Principal


def record(
    session: AsyncSession,
    action: str,
    *,
    principal: Principal | None = None,
    org_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    **meta: Any,
) -> None:
    session.add(
        AuditLog(
            org_id=org_id or (principal.org_id if principal else None),
            workspace_id=workspace_id or (principal.workspace_id if principal else None),
            actor_id=actor_id or (principal.user_id if principal else None),
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            meta=meta,
        )
    )


async def list_entries(
    session: AsyncSession, org_id: uuid.UUID, *, limit: int = 100, before_id: int | None = None
) -> Sequence[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.org_id == org_id)
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)
    return (await session.scalars(stmt.order_by(AuditLog.id.desc()).limit(limit))).all()
