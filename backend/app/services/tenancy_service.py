"""Organizations, workspaces, members and API keys (all scoped by the caller's principal)."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey, Membership, Organization, User, Workspace
from app.security import generate_api_key
from app.services import audit_service
from app.services.auth_service import create_workspace, normalize_email
from app.services.errors import ConflictError, DomainValidationError, ForbiddenError, NotFoundError
from app.services.principal import Principal, Role, role_rank


@dataclass(frozen=True)
class OrgView:
    org: Organization
    role: str
    workspaces: list[Workspace]


async def user_orgs(session: AsyncSession, user_id: uuid.UUID) -> list[OrgView]:
    rows = (
        await session.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at)
        )
    ).all()
    views = []
    for org, role in rows:
        workspaces = (
            await session.scalars(
                select(Workspace).where(Workspace.org_id == org.id).order_by(Workspace.created_at)
            )
        ).all()
        views.append(OrgView(org, role, list(workspaces)))
    return views


# ---- workspaces -----------------------------------------------------------------------


async def list_workspaces(session: AsyncSession, principal: Principal) -> Sequence[Workspace]:
    stmt = select(Workspace).where(Workspace.org_id == principal.org_id)
    return (await session.scalars(stmt.order_by(Workspace.created_at))).all()


async def add_workspace(session: AsyncSession, principal: Principal, name: str) -> Workspace:
    principal.require("admin")
    workspace = await create_workspace(session, principal.org_id, name)
    audit_service.record(
        session,
        "workspace.created",
        principal=principal,
        target_type="workspace",
        target_id=workspace.id,
        name=name,
    )
    await session.commit()
    return workspace


async def get_workspace(session: AsyncSession, principal: Principal) -> Workspace:
    workspace = await session.get(Workspace, principal.workspace_id)
    if workspace is None:
        raise NotFoundError("Workspace not found")
    return workspace


# ---- members --------------------------------------------------------------------------


async def list_members(
    session: AsyncSession, principal: Principal
) -> Sequence[tuple[User, Membership]]:
    rows = await session.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == principal.org_id)
        .order_by(Membership.created_at)
    )
    return [(u, m) for u, m in rows.all()]


def _check_grant(principal: Principal, role: Role) -> None:
    principal.require("admin")
    if role_rank(role) > role_rank(principal.role):
        raise ForbiddenError("You cannot grant a role higher than your own")


async def add_member(
    session: AsyncSession, principal: Principal, email: str, role: Role
) -> tuple[User, Membership]:
    """Add an existing user to the organization (no email invitations in V2)."""
    _check_grant(principal, role)
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        raise DomainValidationError("No user with this email; they must register first")
    if await session.get(Membership, (principal.org_id, user.id)) is not None:
        raise ConflictError("This user is already a member")
    membership = Membership(org_id=principal.org_id, user_id=user.id, role=role)
    session.add(membership)
    audit_service.record(
        session,
        "member.added",
        principal=principal,
        target_type="user",
        target_id=user.id,
        role=role,
    )
    await session.commit()
    return user, membership


async def _owner_count(session: AsyncSession, org_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.org_id == org_id, Membership.role == "owner")
        )
        or 0
    )


async def _target_membership(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID
) -> Membership:
    membership = await session.get(Membership, (principal.org_id, user_id))
    if membership is None:
        raise NotFoundError("Member not found")
    if role_rank(membership.role) > role_rank(principal.role):
        raise ForbiddenError("You cannot change a member with a higher role than yours")
    return membership


async def update_member(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID, role: Role
) -> Membership:
    _check_grant(principal, role)
    membership = await _target_membership(session, principal, user_id)
    if (
        membership.role == "owner"
        and role != "owner"
        and await _owner_count(session, principal.org_id) <= 1
    ):
        raise ConflictError("An organization must keep at least one owner")
    old = membership.role
    membership.role = role
    audit_service.record(
        session,
        "member.role_changed",
        principal=principal,
        target_type="user",
        target_id=user_id,
        old=old,
        new=role,
    )
    await session.commit()
    return membership


async def remove_member(session: AsyncSession, principal: Principal, user_id: uuid.UUID) -> None:
    principal.require("admin")
    membership = await _target_membership(session, principal, user_id)
    if membership.role == "owner" and await _owner_count(session, principal.org_id) <= 1:
        raise ConflictError("An organization must keep at least one owner")
    await session.delete(membership)
    audit_service.record(
        session, "member.removed", principal=principal, target_type="user", target_id=user_id
    )
    await session.commit()


# ---- API keys -------------------------------------------------------------------------


async def list_api_keys(session: AsyncSession, principal: Principal) -> Sequence[ApiKey]:
    """Admins see all keys of the workspace; others only their own."""
    stmt = select(ApiKey).where(ApiKey.workspace_id == principal.workspace_id)
    if not principal.has("admin"):
        stmt = stmt.where(ApiKey.user_id == principal.user_id)
    return (await session.scalars(stmt.order_by(ApiKey.created_at.desc()))).all()


async def create_api_key(
    session: AsyncSession,
    principal: Principal,
    name: str,
    role: Role,
    expires_in_days: int | None,
) -> tuple[ApiKey, str]:
    """Returns the key row and the plaintext token (shown once, never stored)."""
    if principal.via == "api_key":
        raise ForbiddenError("API keys cannot create other API keys")
    principal.require("editor")
    if role_rank(role) > role_rank(principal.role):
        raise ForbiddenError("A key cannot have a higher role than yours")
    generated = generate_api_key()
    key = ApiKey(
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        name=name,
        prefix=generated.prefix,
        key_hash=generated.key_hash,
        role=role,
        expires_at=(datetime.now(UTC) + timedelta(days=expires_in_days))
        if expires_in_days
        else None,
    )
    session.add(key)
    await session.flush()
    audit_service.record(
        session,
        "api_key.created",
        principal=principal,
        target_type="api_key",
        target_id=key.id,
        name=name,
        role=role,
    )
    await session.commit()
    return key, generated.token


async def revoke_api_key(session: AsyncSession, principal: Principal, key_id: uuid.UUID) -> None:
    key = await session.get(ApiKey, key_id)
    if key is None or key.workspace_id != principal.workspace_id:
        raise NotFoundError("API key not found")
    if key.user_id != principal.user_id and not principal.has("admin"):
        raise NotFoundError("API key not found")
    if key.revoked_at is None:
        key.revoked_at = func.now()
        audit_service.record(
            session, "api_key.revoked", principal=principal, target_type="api_key", target_id=key.id
        )
        await session.commit()
