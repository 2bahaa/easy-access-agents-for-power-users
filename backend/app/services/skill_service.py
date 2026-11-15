"""Skill library use cases (skills belong to a workspace; slugs are unique per workspace)."""

import logging
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill, Workspace
from app.schemas.skills import SkillWrite
from app.services.errors import ConflictError, NotFoundError
from app.services.principal import Principal
from app.skills.loader import load_skill_files

logger = logging.getLogger(__name__)


async def list_skills(session: AsyncSession, workspace_id: uuid.UUID) -> Sequence[Skill]:
    stmt = select(Skill).where(Skill.workspace_id == workspace_id).order_by(Skill.name)
    return (await session.scalars(stmt)).all()


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
