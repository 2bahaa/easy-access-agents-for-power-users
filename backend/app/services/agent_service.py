"""Agent management use cases."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from app.config import Settings
from app.db.models import Agent, AgentSkill, AgentTool, Skill
from app.schemas.agents import AgentRead, AgentWrite, ModelParams, ToolSelection
from app.schemas.skills import SkillRef
from app.services.errors import DomainValidationError, NotFoundError


def to_read(agent: Agent) -> AgentRead:
    return AgentRead(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        provider=agent.provider,
        model=agent.model,
        model_params=ModelParams.model_validate(agent.model_params),
        system_prompt=agent.system_prompt,
        skills=[SkillRef.model_validate(link.skill) for link in agent.skill_links],
        tools=[ToolSelection(name=t.tool_name, config=t.config) for t in agent.tool_links],
        max_tool_calls=agent.max_tool_calls,
        run_timeout_s=agent.run_timeout_s,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


async def list_agents(session: AsyncSession) -> Sequence[Agent]:
    stmt = (
        select(Agent)
        .options(raiseload(Agent.skill_links), raiseload(Agent.tool_links))
        .order_by(Agent.updated_at.desc())
    )
    return (await session.scalars(stmt)).all()


async def get_agent(session: AsyncSession, agent_id: uuid.UUID) -> Agent:
    agent = await session.get(Agent, agent_id, populate_existing=True)
    if agent is None:
        raise NotFoundError(f"Agent {agent_id} not found")
    return agent


def _check_limits(data: AgentWrite, settings: Settings) -> None:
    if data.max_tool_calls > settings.max_tool_calls_cap:
        raise DomainValidationError(
            f"max_tool_calls must be <= {settings.max_tool_calls_cap} (global cap)"
        )
    if data.run_timeout_s > settings.run_timeout_cap_s:
        raise DomainValidationError(
            f"run_timeout_s must be <= {settings.run_timeout_cap_s} (global cap)"
        )


async def _resolve_skills(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, Skill]:
    if not ids:
        return {}
    skills = {s.id: s for s in await session.scalars(select(Skill).where(Skill.id.in_(ids)))}
    missing = [str(i) for i in ids if i not in skills]
    if missing:
        raise DomainValidationError(f"Unknown skill id(s): {', '.join(missing)}")
    return skills


def _apply(agent: Agent, data: AgentWrite, skills: dict[uuid.UUID, Skill]) -> None:
    agent.name = data.name
    agent.description = data.description
    agent.provider = data.provider
    agent.model = data.model
    agent.model_params = data.model_params.model_dump(exclude_none=True)
    agent.system_prompt = data.system_prompt
    agent.max_tool_calls = data.max_tool_calls
    agent.run_timeout_s = data.run_timeout_s

    # Reuse existing link rows (same primary key) so full replacement never
    # deletes and re-inserts the same key within one flush.
    old_skills = {link.skill_id: link for link in agent.skill_links}
    skill_links = []
    for position, skill_id in enumerate(data.skill_ids):
        link = old_skills.get(skill_id) or AgentSkill(skill_id=skill_id, skill=skills[skill_id])
        link.position = position
        skill_links.append(link)
    agent.skill_links = skill_links

    # Tool names/configs are validated against the tool registry in Phase 2.
    old_tools = {t.tool_name: t for t in agent.tool_links}
    tool_links = []
    for sel in data.tools:
        tool = old_tools.get(sel.name) or AgentTool(tool_name=sel.name)
        tool.config = sel.config
        tool_links.append(tool)
    agent.tool_links = tool_links


async def create_agent(session: AsyncSession, data: AgentWrite, settings: Settings) -> Agent:
    _check_limits(data, settings)
    skills = await _resolve_skills(session, data.skill_ids)
    agent = Agent(skill_links=[], tool_links=[])
    _apply(agent, data, skills)
    session.add(agent)
    await session.commit()
    return await get_agent(session, agent.id)


async def update_agent(
    session: AsyncSession, agent_id: uuid.UUID, data: AgentWrite, settings: Settings
) -> Agent:
    agent = await get_agent(session, agent_id)
    _check_limits(data, settings)
    skills = await _resolve_skills(session, data.skill_ids)
    _apply(agent, data, skills)
    agent.updated_at = func.now()
    await session.commit()
    return await get_agent(session, agent_id)


async def delete_agent(session: AsyncSession, agent_id: uuid.UUID) -> None:
    agent = await get_agent(session, agent_id)
    await session.delete(agent)  # children go via ON DELETE CASCADE
    await session.commit()
