"""Agent lifecycle beyond CRUD: publish/versions/restore, duplicate, import/export.

Model: the `agents` row is the **draft** (edited by the builder). Publishing freezes it into
an immutable `agent_versions` row holding both the editable config (for diff/restore) and the
resolved runtime config (skill content included), so published behaviour never changes when
skills are edited later. Chat conversations run the latest published version (or the draft
while nothing is published); playground conversations always run the draft.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Agent, AgentVersion, ProviderConnection, Skill
from app.runtime.types import AgentConfig
from app.schemas.agents import AgentWrite
from app.schemas.platform import (
    AgentExportDocument,
    AgentStatus,
    ExportedAgent,
    ExportedSkill,
    ImportResult,
)
from app.schemas.skills import SkillWrite
from app.services import agent_service, audit_service, skill_service
from app.services.errors import DomainValidationError, NotFoundError
from app.services.principal import Principal
from app.services.provider_service import ProviderResolver
from app.tools.registry import ToolRegistry


def write_config(agent: Agent) -> dict[str, Any]:
    """The draft as an AgentWrite payload (JSON-compatible)."""
    read = agent_service.to_read(agent)
    return AgentWrite(
        name=read.name,
        description=read.description,
        provider=read.provider,
        connection_id=read.connection_id,
        model=read.model,
        model_params=read.model_params,
        system_prompt=read.system_prompt,
        skill_ids=[s.id for s in read.skills],
        tools=read.tools,
        max_tool_calls=read.max_tool_calls,
        run_timeout_s=read.run_timeout_s,
    ).model_dump(mode="json")


async def latest_version(session: AsyncSession, agent_id: uuid.UUID) -> AgentVersion | None:
    return await session.scalar(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version.desc())
        .limit(1)
    )


async def status(session: AsyncSession, agent: Agent) -> AgentStatus:
    latest = await latest_version(session, agent.id)
    return AgentStatus(
        published_version=latest.version if latest else None,
        has_unpublished_changes=latest is None or latest.write_config != write_config(agent),
    )


async def runtime_config_for_chat(
    session: AsyncSession, agent: Agent, playground: bool
) -> tuple[AgentConfig, int | None]:
    """Config a new run executes, and the version number (None = the draft)."""
    from app.services.run_service import to_agent_config

    if not playground:
        latest = await latest_version(session, agent.id)
        if latest is not None:
            return AgentConfig.model_validate(latest.runtime_config), latest.version
    return to_agent_config(agent), None


async def publish(
    session: AsyncSession, principal: Principal, agent_id: uuid.UUID, note: str
) -> AgentVersion:
    from app.services.run_service import to_agent_config

    principal.require("editor")
    agent = await agent_service.get_agent(session, agent_id, principal.workspace_id)
    current = await session.scalar(
        select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent_id)
    )
    version = AgentVersion(
        agent_id=agent_id,
        version=(current or 0) + 1,
        write_config=write_config(agent),
        runtime_config=to_agent_config(agent).model_dump(mode="json"),
        note=note,
        created_by=principal.user_id,
    )
    session.add(version)
    audit_service.record(
        session,
        "agent.published",
        principal=principal,
        target_type="agent",
        target_id=agent_id,
        version=version.version,
    )
    await session.commit()
    return version


async def list_versions(
    session: AsyncSession, principal: Principal, agent_id: uuid.UUID
) -> Sequence[AgentVersion]:
    await agent_service.get_agent(session, agent_id, principal.workspace_id)
    stmt = (
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version.desc())
    )
    return (await session.scalars(stmt)).all()


async def get_version(
    session: AsyncSession, principal: Principal, agent_id: uuid.UUID, version: int
) -> AgentVersion:
    await agent_service.get_agent(session, agent_id, principal.workspace_id)
    row = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id, AgentVersion.version == version
        )
    )
    if row is None:
        raise NotFoundError(f"Version {version} not found")
    return row


async def restore(
    session: AsyncSession,
    principal: Principal,
    agent_id: uuid.UUID,
    version: int,
    *,
    settings: Settings,
    registry: ToolRegistry,
    resolver: ProviderResolver,
) -> tuple[Agent, list[str]]:
    """Copy a published version into the draft (re-validated). Skills deleted since are
    dropped and reported."""
    row = await get_version(session, principal, agent_id, version)
    data = AgentWrite.model_validate(row.write_config)
    existing = set(
        await session.scalars(
            select(Skill.id).where(
                Skill.id.in_(data.skill_ids), Skill.workspace_id == principal.workspace_id
            )
        )
    )
    dropped = [str(s) for s in data.skill_ids if s not in existing]
    data = data.model_copy(update={"skill_ids": [s for s in data.skill_ids if s in existing]})
    agent = await agent_service.update_agent(
        session, principal, agent_id, data, settings, registry, resolver
    )
    audit_service.record(
        session,
        "agent.restored",
        principal=principal,
        target_type="agent",
        target_id=agent_id,
        version=version,
    )
    await session.commit()
    return agent, dropped


async def duplicate(
    session: AsyncSession,
    principal: Principal,
    agent_id: uuid.UUID,
    name: str | None,
    *,
    settings: Settings,
    registry: ToolRegistry,
    resolver: ProviderResolver,
) -> Agent:
    source = await agent_service.get_agent(session, agent_id, principal.workspace_id)
    data = AgentWrite.model_validate(write_config(source))
    data = data.model_copy(update={"name": (name or f"Copy of {source.name}")[:100]})
    return await agent_service.create_agent(session, principal, data, settings, registry, resolver)


# ---- import / export --------------------------------------------------------------------


async def export_agent(
    session: AsyncSession, principal: Principal, agent_id: uuid.UUID
) -> AgentExportDocument:
    agent = await agent_service.get_agent(session, agent_id, principal.workspace_id)
    connection_name = None
    if agent.connection_id is not None:
        conn = await session.get(ProviderConnection, agent.connection_id)
        connection_name = conn.name if conn else None
    read = agent_service.to_read(agent)
    skills = [link.skill for link in agent.skill_links]
    return AgentExportDocument(
        exported_at=datetime.now(UTC),
        agent=ExportedAgent(
            name=read.name,
            description=read.description,
            provider_kind=read.provider,
            connection_name=connection_name,
            model=read.model,
            model_params=read.model_params,
            system_prompt=read.system_prompt,
            skills=[s.slug for s in skills],
            tools=read.tools,
            max_tool_calls=read.max_tool_calls,
            run_timeout_s=read.run_timeout_s,
        ),
        skills=[
            ExportedSkill(
                slug=s.slug,
                name=s.name,
                description=s.description,
                content_md=s.content_md,
                category=s.category,
                tags=list(s.tags),
            )
            for s in skills
        ],
    )


async def import_agent(
    session: AsyncSession,
    principal: Principal,
    doc: AgentExportDocument,
    *,
    settings: Settings,
    registry: ToolRegistry,
    resolver: ProviderResolver,
) -> ImportResult:
    """Create an agent from an export document. Skills are matched by slug in the workspace
    (existing ones are reused, never overwritten); the provider connection by name."""
    principal.require("editor")
    a = doc.agent
    defined = {s.slug: s for s in doc.skills}
    missing = [slug for slug in a.skills if slug not in defined]
    if missing:
        raise DomainValidationError(f"Skills referenced but not included: {', '.join(missing)}")

    connection_id = None
    if a.connection_name:
        conn = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == principal.workspace_id,
                ProviderConnection.name == a.connection_name,
            )
        )
        if conn is None:
            raise DomainValidationError(
                f"This agent uses a provider named '{a.connection_name}' ({a.provider_kind}). "
                "Add a provider with that name first, then import again."
            )
        connection_id = conn.id

    data = AgentWrite(
        name=a.name,
        description=a.description,
        provider=a.provider_kind if connection_id is None else "ollama",
        connection_id=connection_id,
        model=a.model,
        model_params=a.model_params,
        system_prompt=a.system_prompt,
        skill_ids=[],
        tools=a.tools,
        max_tool_calls=a.max_tool_calls,
        run_timeout_s=a.run_timeout_s,
    )
    # Validate the agent before creating anything, so a failed import leaves no skills behind.
    agent_service.check_limits(data, settings)
    agent_service.validate_tools(data, registry)
    await agent_service.check_provider_and_model(session, principal, data, resolver)

    skill_ids: list[uuid.UUID] = []
    created, reused = [], []
    for slug in a.skills:
        existing = await session.scalar(
            select(Skill).where(Skill.workspace_id == principal.workspace_id, Skill.slug == slug)
        )
        if existing is not None:
            skill_ids.append(existing.id)
            reused.append(slug)
            continue
        s = defined[slug]
        skill = await skill_service.create_skill(
            session,
            principal,
            SkillWrite(
                slug=s.slug,
                name=s.name,
                description=s.description,
                content_md=s.content_md,
                category=s.category,
                tags=s.tags,
            ),
        )
        skill_ids.append(skill.id)
        created.append(slug)

    data = data.model_copy(update={"skill_ids": skill_ids})
    agent = await agent_service.create_agent(session, principal, data, settings, registry, resolver)
    audit_service.record(
        session, "agent.imported", principal=principal, target_type="agent", target_id=agent.id
    )
    await session.commit()
    return ImportResult(agent_id=agent.id, created_skills=created, reused_skills=reused)
