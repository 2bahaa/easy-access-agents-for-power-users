"""Agent management use cases (always scoped to one workspace)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from app.config import Settings
from app.db.models import Agent, AgentSkill, AgentTool, Skill
from app.runtime.providers.base import ProviderError
from app.schemas.agents import AgentRead, AgentWrite, ModelParams, ToolSelection
from app.schemas.skills import SkillRef
from app.services import audit_service, capability_service, provider_service
from app.services.errors import ConflictError, DomainValidationError, NotFoundError
from app.services.principal import Principal
from app.services.provider_service import ProviderResolver
from app.tools.external import is_external
from app.tools.registry import ToolConfigError, ToolRegistry, UnknownToolError


def to_read(agent: Agent) -> AgentRead:
    return AgentRead(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        provider=agent.provider,
        connection_id=agent.connection_id,
        model=agent.model,
        model_params=ModelParams.model_validate(agent.model_params),
        system_prompt=agent.system_prompt,
        skills=[SkillRef.model_validate(link.skill) for link in agent.skill_links],
        tools=[
            ToolSelection(name=t.tool_name, config=t.config, requires_approval=t.requires_approval)
            for t in agent.tool_links
        ],
        max_tool_calls=agent.max_tool_calls,
        run_timeout_s=agent.run_timeout_s,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


async def list_agents(session: AsyncSession, workspace_id: uuid.UUID) -> Sequence[Agent]:
    stmt = (
        select(Agent)
        .where(Agent.workspace_id == workspace_id)
        .options(raiseload(Agent.skill_links), raiseload(Agent.tool_links))
        .order_by(Agent.updated_at.desc())
    )
    return (await session.scalars(stmt)).all()


async def get_agent(session: AsyncSession, agent_id: uuid.UUID, workspace_id: uuid.UUID) -> Agent:
    """404 for unknown ids *and* for agents of other workspaces (no existence leak)."""
    agent = await session.get(Agent, agent_id, populate_existing=True)
    if agent is None or agent.workspace_id != workspace_id:
        raise NotFoundError(f"Agent {agent_id} not found")
    return agent


def check_limits(data: AgentWrite, settings: Settings) -> None:
    if data.max_tool_calls > settings.max_tool_calls_cap:
        raise DomainValidationError(
            f"max_tool_calls must be <= {settings.max_tool_calls_cap} (global cap)"
        )
    if data.run_timeout_s > settings.run_timeout_cap_s:
        raise DomainValidationError(
            f"run_timeout_s must be <= {settings.run_timeout_cap_s} (global cap)"
        )


async def _resolve_skills(
    session: AsyncSession, ids: list[uuid.UUID], workspace_id: uuid.UUID
) -> dict[uuid.UUID, Skill]:
    if not ids:
        return {}
    stmt = select(Skill).where(Skill.id.in_(ids), Skill.workspace_id == workspace_id)
    skills = {s.id: s for s in await session.scalars(stmt)}
    missing = [str(i) for i in ids if i not in skills]
    if missing:
        raise DomainValidationError(f"Unknown skill id(s): {', '.join(missing)}")
    return skills


def validate_tools(data: AgentWrite, registry: ToolRegistry) -> dict[str, dict[str, Any]]:
    """Return {tool_name: canonical config}; raise 422 for unknown tools or bad configs."""
    configs: dict[str, dict[str, Any]] = {}
    for sel in data.tools:
        if is_external(sel.name):  # validated against the workspace in validate_external_tools
            configs[sel.name] = sel.config
            continue
        try:
            configs[sel.name] = registry.normalize_config(sel.name, sel.config)
        except UnknownToolError:
            raise DomainValidationError(f"Unknown tool: '{sel.name}'") from None
        except ToolConfigError as e:
            raise DomainValidationError(str(e)) from None
    return configs


async def validate_external_tools(
    session: AsyncSession,
    principal: Principal,
    configs: dict[str, dict[str, Any]],
    settings: Settings,
    resolver: ProviderResolver,
) -> dict[str, dict[str, Any]]:
    out = dict(configs)
    for name, config in configs.items():
        if is_external(name):
            out[name] = await capability_service.normalize_external_grant(
                session, principal.workspace_id, settings, resolver.secrets, name, config
            )
    return out


async def check_provider_and_model(
    session: AsyncSession, principal: Principal, data: AgentWrite, resolver: ProviderResolver
) -> str:
    """Resolve the agent's provider (workspace-scoped) and return its kind."""
    kind = data.provider
    if data.connection_id is not None:
        try:
            conn = await provider_service.get_connection(
                session, principal.workspace_id, data.connection_id
            )
        except NotFoundError:
            raise DomainValidationError(
                f"Unknown provider connection: {data.connection_id}"
            ) from None
        kind = conn.kind
    provider = await resolver.resolve(
        session, principal.workspace_id, data.provider, data.connection_id
    )
    provider_service.validate_params_for_kind(kind, data.model_params.model_dump())
    if not data.tools:
        return kind
    try:
        caps = await provider.get_capabilities(data.model)
    except ProviderError:
        # Provider offline or model not pulled yet: allow saving; the run pre-flight
        # check enforces tool support before any execution.
        return kind
    if caps.supports_tools is None:
        return kind  # unknown: saving allowed; the run pre-flight refuses until confirmed
    if not caps.supports_tools:
        raise ConflictError(
            f"Model '{data.model}' does not support tool calling; remove the tools "
            "or choose a tool-capable model"
        )
    return kind


def _apply(
    agent: Agent,
    data: AgentWrite,
    kind: str,
    skills: dict[uuid.UUID, Skill],
    tool_configs: dict[str, dict[str, Any]],
) -> None:
    agent.name = data.name
    agent.description = data.description
    agent.provider = kind if data.connection_id is not None else data.provider
    agent.connection_id = data.connection_id
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

    old_tools = {t.tool_name: t for t in agent.tool_links}
    approval = {sel.name: sel.requires_approval for sel in data.tools}
    tool_links = []
    for name, config in tool_configs.items():
        tool = old_tools.get(name) or AgentTool(tool_name=name)
        tool.config = config
        tool.requires_approval = approval.get(name, False)
        tool_links.append(tool)
    agent.tool_links = tool_links


async def create_agent(
    session: AsyncSession,
    principal: Principal,
    data: AgentWrite,
    settings: Settings,
    registry: ToolRegistry,
    resolver: ProviderResolver,
) -> Agent:
    principal.require("editor")
    check_limits(data, settings)
    tool_configs = validate_tools(data, registry)
    tool_configs = await validate_external_tools(
        session, principal, tool_configs, settings, resolver
    )
    kind = await check_provider_and_model(session, principal, data, resolver)
    skills = await _resolve_skills(session, data.skill_ids, principal.workspace_id)
    agent = Agent(workspace_id=principal.workspace_id, skill_links=[], tool_links=[])
    _apply(agent, data, kind, skills, tool_configs)
    session.add(agent)
    await session.commit()
    return await get_agent(session, agent.id, principal.workspace_id)


async def update_agent(
    session: AsyncSession,
    principal: Principal,
    agent_id: uuid.UUID,
    data: AgentWrite,
    settings: Settings,
    registry: ToolRegistry,
    resolver: ProviderResolver,
) -> Agent:
    principal.require("editor")
    agent = await get_agent(session, agent_id, principal.workspace_id)
    check_limits(data, settings)
    tool_configs = validate_tools(data, registry)
    tool_configs = await validate_external_tools(
        session, principal, tool_configs, settings, resolver
    )
    kind = await check_provider_and_model(session, principal, data, resolver)
    skills = await _resolve_skills(session, data.skill_ids, principal.workspace_id)
    _apply(agent, data, kind, skills, tool_configs)
    agent.updated_at = func.now()
    await session.commit()
    return await get_agent(session, agent_id, principal.workspace_id)


async def delete_agent(session: AsyncSession, principal: Principal, agent_id: uuid.UUID) -> None:
    principal.require("editor")
    agent = await get_agent(session, agent_id, principal.workspace_id)
    await session.delete(agent)  # children go via ON DELETE CASCADE
    audit_service.record(
        session,
        "agent.deleted",
        principal=principal,
        target_type="agent",
        target_id=agent_id,
        name=agent.name,
    )
    await session.commit()
