"""Skill library use cases (skills belong to a workspace; slugs are unique per workspace)."""

import logging
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill, SkillVersion, Workspace
from app.schemas.skills import SkillWrite
from app.services.errors import ConflictError, DomainValidationError, NotFoundError
from app.services.principal import Principal
from app.skills.loader import SkillFileError, load_skill_files, parse_skill_markdown

logger = logging.getLogger(__name__)


async def list_skills(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    q: str | None = None,
    tag: str | None = None,
    category: str | None = None,
) -> Sequence[Skill]:
    stmt = select(Skill).where(Skill.workspace_id == workspace_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Skill.name.ilike(like), Skill.description.ilike(like), Skill.slug.ilike(like))
        )
    if tag:
        stmt = stmt.where(Skill.tags.contains([tag.strip().lower()]))
    if category:
        stmt = stmt.where(Skill.category == category)
    return (await session.scalars(stmt.order_by(Skill.name))).all()


async def get_skill(session: AsyncSession, skill_id: uuid.UUID, workspace_id: uuid.UUID) -> Skill:
    skill = await session.get(Skill, skill_id, populate_existing=True)
    if skill is None or skill.workspace_id != workspace_id:
        raise NotFoundError(f"Skill {skill_id} not found")
    return skill


async def _ensure_slug_free(
    session: AsyncSession, workspace_id: uuid.UUID, slug: str, exclude_id: uuid.UUID | None = None
) -> None:
    stmt = select(Skill.id).where(Skill.workspace_id == workspace_id, Skill.slug == slug)
    if exclude_id is not None:
        stmt = stmt.where(Skill.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise ConflictError(f"Skill slug '{slug}' already exists")


async def _commit(session: AsyncSession, slug: str) -> None:
    try:
        await session.commit()
    except IntegrityError as e:  # race on the unique slug constraint
        await session.rollback()
        raise ConflictError(f"Skill slug '{slug}' already exists") from e


async def create_skill(session: AsyncSession, principal: Principal, data: SkillWrite) -> Skill:
    principal.require("editor")
    await _ensure_slug_free(session, principal.workspace_id, data.slug)
    skill = Skill(**data.model_dump(), workspace_id=principal.workspace_id, is_builtin=False)
    session.add(skill)
    await _commit(session, data.slug)
    return await get_skill(session, skill.id, principal.workspace_id)


async def update_skill(
    session: AsyncSession, principal: Principal, skill_id: uuid.UUID, data: SkillWrite
) -> Skill:
    principal.require("editor")
    skill = await get_skill(session, skill_id, principal.workspace_id)
    await _ensure_slug_free(session, principal.workspace_id, data.slug, exclude_id=skill_id)
    content_changed = (skill.name, skill.description, skill.content_md) != (
        data.name,
        data.description,
        data.content_md,
    )
    if content_changed:  # keep the previous state, then bump the version
        session.add(
            SkillVersion(
                skill_id=skill.id,
                version=skill.version,
                name=skill.name,
                description=skill.description,
                content_md=skill.content_md,
                created_by=principal.user_id,
            )
        )
        skill.version += 1
    for field, value in data.model_dump().items():
        setattr(skill, field, value)
    skill.updated_at = func.now()
    await _commit(session, data.slug)
    return await get_skill(session, skill_id, principal.workspace_id)


async def delete_skill(session: AsyncSession, principal: Principal, skill_id: uuid.UUID) -> None:
    principal.require("editor")
    skill = await get_skill(session, skill_id, principal.workspace_id)
    await session.delete(skill)  # agent_skills rows go via ON DELETE CASCADE
    await session.commit()


async def seed_builtin_skills(
    session: AsyncSession, directory: Path, workspace_id: uuid.UUID | None = None
) -> int:
    """Insert built-in skills missing from a workspace (all workspaces if None).
    Never overwrites user edits."""
    files = load_skill_files(directory)
    if not files:
        return 0
    workspace_ids = (
        [workspace_id]
        if workspace_id is not None
        else list(await session.scalars(select(Workspace.id)))
    )
    added: list[Skill] = []
    for ws in workspace_ids:
        existing = set(await session.scalars(select(Skill.slug).where(Skill.workspace_id == ws)))
        added += [
            Skill(**f.model_dump(), workspace_id=ws, is_builtin=True)
            for f in files
            if f.slug not in existing
        ]
    session.add_all(added)
    await session.commit()
    if added:
        logger.info("Seeded %d built-in skill(s)", len(added))
    return len(added)


async def list_versions(
    session: AsyncSession, principal: Principal, skill_id: uuid.UUID
) -> Sequence[SkillVersion]:
    await get_skill(session, skill_id, principal.workspace_id)
    stmt = (
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill_id)
        .order_by(SkillVersion.version.desc())
    )
    return (await session.scalars(stmt)).all()


async def restore_version(
    session: AsyncSession, principal: Principal, skill_id: uuid.UUID, version: int
) -> Skill:
    """Make an earlier version current again (recorded as a new version)."""
    skill = await get_skill(session, skill_id, principal.workspace_id)
    old = await session.scalar(
        select(SkillVersion).where(
            SkillVersion.skill_id == skill_id, SkillVersion.version == version
        )
    )
    if old is None:
        raise NotFoundError(f"Version {version} of skill {skill_id} not found")
    data = SkillWrite(
        slug=skill.slug,
        name=old.name,
        description=old.description,
        content_md=old.content_md,
        category=skill.category,
        tags=list(skill.tags),
    )
    return await update_skill(session, principal, skill_id, data)


def to_write(skill: Skill) -> SkillWrite:
    return SkillWrite(
        slug=skill.slug,
        name=skill.name,
        description=skill.description,
        content_md=skill.content_md,
        category=skill.category,
        tags=list(skill.tags),
    )


async def import_markdown(session: AsyncSession, principal: Principal, markdown: str) -> Skill:
    try:
        data = parse_skill_markdown(markdown, source="import")
    except SkillFileError as e:
        raise DomainValidationError(str(e)) from e
    return await create_skill(session, principal, data)


def templates(directory: Path) -> list[SkillWrite]:
    """Built-in skill files, offered as starting points for new skills."""
    return load_skill_files(directory)
