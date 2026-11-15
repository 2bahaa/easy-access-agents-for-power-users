"""Authentication: registration, login, refresh-token rotation, principal resolution.

* Access tokens: short-lived HS256 JWTs (`sub` = user id). Sent as `Authorization: Bearer`.
* Refresh tokens: opaque, stored hashed, rotated on every use. Presenting an already-rotated
  token revokes its whole family (token theft detection).
* API keys: `eaa_<prefix>_<secret>`, workspace-scoped, role capped by the creator's role.
* The workspace of a token request comes from `X-Workspace-Id` (default: the user's first
  workspace); membership in the workspace's organization is always checked.
"""

import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import ApiKey, Membership, Organization, RefreshToken, User, Workspace
from app.security import (
    DUMMY_PASSWORD_HASH,
    api_key_matches,
    create_access_token,
    decode_access_token,
    hash_password,
    new_opaque_token,
    parse_api_key,
    sha256_hex,
    verify_password,
)
from app.services import audit_service
from app.services.errors import ConflictError, ForbiddenError, UnauthorizedError
from app.services.principal import Principal, role_rank

logger = logging.getLogger(__name__)

# Organization/workspace created by migration 0003 to own pre-existing (MVP) data.
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_EPHEMERAL_SECRET = secrets.token_urlsafe(48)


def jwt_secret(settings: Settings) -> str:
    secret = settings.jwt_secret.get_secret_value()
    return secret or _EPHEMERAL_SECRET


def normalize_email(email: str) -> str:
    return email.strip().lower()


def workspace_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


# ---- registration & login -----------------------------------------------------------


async def create_workspace(session: AsyncSession, org_id: uuid.UUID, name: str) -> Workspace:
    """Create a workspace (caller commits). Built-in skills are seeded by the caller."""
    workspace = Workspace(org_id=org_id, name=name, slug=workspace_slug(name))
    session.add(workspace)
    await session.flush()
    return workspace


async def register(
    session: AsyncSession, settings: Settings, email: str, password: str, name: str
) -> tuple[User, Workspace]:
    """Create a user. The very first user becomes owner of the Default organization (which
    holds pre-existing data); later users get their own organization and workspace."""
    email = normalize_email(email)
    first_user = (await session.scalar(select(func.count()).select_from(User))) == 0
    if not first_user and not settings.allow_registration:
        raise ForbiddenError("Registration is disabled on this server")
    if await session.scalar(select(User.id).where(User.email == email)) is not None:
        raise ConflictError("An account with this email already exists")

    user = User(email=email, name=name.strip(), password_hash=hash_password(password))
    session.add(user)
    await session.flush()

    default_org = await session.get(Organization, DEFAULT_ORG_ID) if first_user else None
    if default_org is not None:
        org = default_org
        workspace = await session.scalar(
            select(Workspace).where(Workspace.org_id == org.id).order_by(Workspace.created_at)
        )
        if workspace is None:
            workspace = await create_workspace(session, org.id, "Default")
    else:
        org = Organization(name=f"{name.strip() or email.split('@')[0]}'s organization")
        session.add(org)
        await session.flush()
        workspace = await create_workspace(session, org.id, "Personal")
    session.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    audit_service.record(
        session,
        "user.registered",
        org_id=org.id,
        workspace_id=workspace.id,
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
    )
    try:
        await session.commit()
    except IntegrityError:  # concurrent registration with the same email
        await session.rollback()
        raise ConflictError("An account with this email already exists") from None
    return user, workspace


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    # Always run one hash verification so timing does not reveal whether the email exists.
    valid = verify_password(user.password_hash if user else DUMMY_PASSWORD_HASH, password)
    if user is None or not valid or not user.is_active:
        audit_service.record(
            session, "auth.login_failed", actor_id=user.id if user else None, email=email[:254]
        )
        await session.commit()
        raise UnauthorizedError("Invalid email or password")
    audit_service.record(
        session, "auth.login", actor_id=user.id, target_type="user", target_id=user.id
    )
    return user


async def issue_tokens(
    session: AsyncSession, settings: Settings, user: User, family_id: uuid.UUID | None = None
) -> TokenPair:
    """Create an access token and a new refresh token (caller's transaction is committed)."""
    access, access_exp = create_access_token(
        jwt_secret(settings), user.id, settings.access_token_ttl_s
    )
    refresh = new_opaque_token()
    refresh_exp = datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=sha256_hex(refresh),
            expires_at=refresh_exp,
        )
    )
    await session.commit()
    return TokenPair(access, access_exp, refresh, refresh_exp)


async def rotate_refresh_token(
    session: AsyncSession, settings: Settings, token: str | None
) -> tuple[User, TokenPair]:
    if not token:
        raise UnauthorizedError("Not signed in")
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(token)).with_for_update()
    )
    if row is None:
        raise UnauthorizedError("Session expired; sign in again")
    if row.revoked_at is not None:
        # A rotated token was presented again: assume theft and end the whole session family.
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        audit_service.record(session, "auth.refresh_reuse_detected", actor_id=row.user_id)
        await session.commit()
        logger.warning("Refresh token reuse detected for user %s", row.user_id)
        raise UnauthorizedError("Session expired; sign in again")
    if row.expires_at <= datetime.now(UTC):
        raise UnauthorizedError("Session expired; sign in again")
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Session expired; sign in again")
    row.revoked_at = func.now()
    return user, await issue_tokens(session, settings, user, family_id=row.family_id)


async def revoke_refresh_token(session: AsyncSession, token: str | None) -> None:
    if not token:
        return
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(token))
    )
    if row is not None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        audit_service.record(session, "auth.logout", actor_id=row.user_id)
        await session.commit()


# ---- principal resolution -----------------------------------------------------------


async def _membership_role(
    session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
) -> str | None:
    return await session.scalar(
        select(Membership.role).where(Membership.user_id == user_id, Membership.org_id == org_id)
    )


async def _principal_from_api_key(session: AsyncSession, token: str) -> Principal:
    prefix = parse_api_key(token)
    key = await session.scalar(select(ApiKey).where(ApiKey.prefix == prefix)) if prefix else None
    now = datetime.now(UTC)
    if (
        key is None
        or key.revoked_at is not None
        or (key.expires_at is not None and key.expires_at <= now)
        or not api_key_matches(token, key.key_hash)
    ):
        raise UnauthorizedError("Invalid API key")
    workspace = await session.get(Workspace, key.workspace_id)
    user = await session.get(User, key.user_id)
    if workspace is None or user is None or not user.is_active:
        raise UnauthorizedError("Invalid API key")
    member_role = await _membership_role(session, user.id, workspace.org_id)
    if member_role is None:  # the key's owner left the organization
        raise UnauthorizedError("Invalid API key")
    # A key never has more rights than its owner currently has.
    role = key.role if role_rank(key.role) <= role_rank(member_role) else member_role
    if key.last_used_at is None or now - key.last_used_at > timedelta(minutes=1):
        key.last_used_at = now
        await session.commit()
    return Principal(user.id, workspace.org_id, workspace.id, role, via="api_key")


async def resolve_principal(
    session: AsyncSession, settings: Settings, bearer: str | None, workspace_id: str | None
) -> Principal:
    if not bearer:
        raise UnauthorizedError("Authentication required")
    if bearer.startswith("eaa_"):
        return await _principal_from_api_key(session, bearer)

    claims = decode_access_token(jwt_secret(settings), bearer)
    if claims is None:
        raise UnauthorizedError("Invalid or expired access token")
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid or expired access token")

    if workspace_id:
        try:
            ws_uuid = uuid.UUID(workspace_id)
        except ValueError:
            raise ForbiddenError("Unknown workspace") from None
        workspace = await session.get(Workspace, ws_uuid)
    else:  # default: first workspace of the user's oldest membership
        workspace = await session.scalar(
            select(Workspace)
            .join(Membership, Membership.org_id == Workspace.org_id)
            .where(Membership.user_id == user.id)
            .order_by(Membership.created_at, Workspace.created_at)
            .limit(1)
        )
    if workspace is None:
        raise ForbiddenError("Unknown workspace")
    role = await _membership_role(session, user.id, workspace.org_id)
    if role is None:  # same error as unknown: do not reveal other tenants' workspaces
        raise ForbiddenError("Unknown workspace")
    return Principal(user.id, workspace.org_id, workspace.id, role)
