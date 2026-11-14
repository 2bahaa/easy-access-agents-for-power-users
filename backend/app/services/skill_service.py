"""Skill library use cases."""

import logging
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill
from app.schemas.skills import SkillWrite
from app.services.errors import ConflictError, NotFoundError
from app.skills.loader import load_skill_files

logger = logging.getLogger(__name__)


async def list_skills(session: AsyncSession) -> Sequence[Skill]:
    result = await session.scalars(select(Skill).order_by(Skill.name))
    return result.all()


async def get_skill(session: AsyncSession, skill_id: uuid.UUID) -> Skill:
    skill = await session.get(Skill, skill_id, populate_existing=True)
    if skill is None:
        raise NotFoundError(f"Skill {skill_id} not found")
    return skill


async def _ensure_slug_free(
    session: AsyncSession, slug: str, exclude_id: uuid.UUID | None = None
) -> None:
    stmt = select(Skill.id).where(Skill.slug == slug)
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


async def create_skill(session: AsyncSession, data: SkillWrite) -> Skill:
    await _ensure_slug_free(session, data.slug)
    skill = Skill(**data.model_dump(), is_builtin=False)
    session.add(skill)
    await _commit(session, data.slug)
    return await get_skill(session, skill.id)


async def update_skill(session: AsyncSession, skill_id: uuid.UUID, data: SkillWrite) -> Skill:
    skill = await get_skill(session, skill_id)
    await _ensure_slug_free(session, data.slug, exclude_id=skill_id)
    for field, value in data.model_dump().items():
        setattr(skill, field, value)
    skill.updated_at = func.now()
    await _commit(session, data.slug)
    return await get_skill(session, skill_id)


async def delete_skill(session: AsyncSession, skill_id: uuid.UUID) -> None:
    skill = await get_skill(session, skill_id)
    await session.delete(skill)  # agent_skills rows go via ON DELETE CASCADE
    await session.commit()


async def seed_builtin_skills(session: AsyncSession, directory: Path) -> int:
    """Insert built-in skills whose slug is not yet in the DB. Never overwrites user edits."""
    files = load_skill_files(directory)
    if not files:
        return 0
    existing = set(await session.scalars(select(Skill.slug)))
    added = [Skill(**f.model_dump(), is_builtin=True) for f in files if f.slug not in existing]
    session.add_all(added)
    await session.commit()
    if added:
        logger.info("Seeded %d built-in skill(s)", len(added))
    return len(added)
