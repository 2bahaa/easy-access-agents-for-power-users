import uuid

from fastapi import APIRouter, status

from app.agents_templates import TEMPLATES
from app.api.deps import (
    PrincipalDep,
    ProviderResolverDep,
    SessionDep,
    SettingsDep,
    ToolRegistryDep,
)
from app.db.models import Agent
from app.schemas.agents import AgentRead, AgentSummary, AgentWrite
from app.schemas.platform import (
    AgentExportDocument,
    AgentTemplate,
    AgentVersionRead,
    AgentVersionSummary,
    DuplicateRequest,
    ImportResult,
    PublishRequest,
)
from app.services import agent_platform, agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


async def _read(session: SessionDep, agent: Agent) -> AgentRead:
    status = await agent_platform.status(session, agent)
    return agent_service.to_read(agent).model_copy(update=status.model_dump())


@router.get("")
async def list_agents(principal: PrincipalDep, session: SessionDep) -> list[AgentSummary]:
    agents = await agent_service.list_agents(session, principal.workspace_id)
    return [AgentSummary.model_validate(a) for a in agents]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    data: AgentWrite,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
    resolver: ProviderResolverDep,
) -> AgentRead:
    agent = await agent_service.create_agent(session, principal, data, settings, registry, resolver)
    return agent_service.to_read(agent)


@router.get("/{agent_id}")
async def get_agent(agent_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> AgentRead:
    agent = await agent_service.get_agent(session, agent_id, principal.workspace_id)
    return await _read(session, agent)


@router.put("/{agent_id}")
async def update_agent(
    agent_id: uuid.UUID,
    data: AgentWrite,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
    resolver: ProviderResolverDep,
) -> AgentRead:
    agent = await agent_service.update_agent(
        session, principal, agent_id, data, settings, registry, resolver
    )
    return await _read(session, agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await agent_service.delete_agent(session, principal, agent_id)


# ---- templates, duplicate, import/export, versions --------------------------------------

templates_router = APIRouter(tags=["agents"])


@templates_router.get("/agent-templates")
async def list_templates(principal: PrincipalDep) -> list[AgentTemplate]:
    return TEMPLATES


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_agent(
    doc: AgentExportDocument,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
    resolver: ProviderResolverDep,
) -> ImportResult:
    return await agent_platform.import_agent(
        session, principal, doc, settings=settings, registry=registry, resolver=resolver
    )


@router.get("/{agent_id}/export")
async def export_agent(
    agent_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> AgentExportDocument:
    return await agent_platform.export_agent(session, principal, agent_id)


@router.post("/{agent_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_agent(
    agent_id: uuid.UUID,
    data: DuplicateRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
    resolver: ProviderResolverDep,
) -> AgentRead:
    agent = await agent_platform.duplicate(
        session,
        principal,
        agent_id,
        data.name,
        settings=settings,
        registry=registry,
        resolver=resolver,
    )
    return await _read(session, agent)


@router.post("/{agent_id}/publish", status_code=status.HTTP_201_CREATED)
async def publish_agent(
    agent_id: uuid.UUID, data: PublishRequest, principal: PrincipalDep, session: SessionDep
) -> AgentVersionSummary:
    version = await agent_platform.publish(session, principal, agent_id, data.note)
    return AgentVersionSummary.model_validate(version)


@router.get("/{agent_id}/versions")
async def list_versions(
    agent_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[AgentVersionSummary]:
    versions = await agent_platform.list_versions(session, principal, agent_id)
    return [AgentVersionSummary.model_validate(v) for v in versions]


@router.get("/{agent_id}/versions/{version}")
async def get_version(
    agent_id: uuid.UUID, version: int, principal: PrincipalDep, session: SessionDep
) -> AgentVersionRead:
    row = await agent_platform.get_version(session, principal, agent_id, version)
    return AgentVersionRead.model_validate(row)


@router.post("/{agent_id}/versions/{version}/restore")
async def restore_version(
    agent_id: uuid.UUID,
    version: int,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
    resolver: ProviderResolverDep,
) -> AgentRead:
    """Copy a published version into the draft (publish again to make it live)."""
    agent, _dropped = await agent_platform.restore(
        session,
        principal,
        agent_id,
        version,
        settings=settings,
        registry=registry,
        resolver=resolver,
    )
    return await _read(session, agent)
