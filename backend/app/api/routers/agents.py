import uuid

from fastapi import APIRouter, status

from app.api.deps import (
    PrincipalDep,
    ProviderRegistryDep,
    SessionDep,
    SettingsDep,
    ToolRegistryDep,
)
from app.schemas.agents import AgentRead, AgentSummary, AgentWrite
from app.services import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


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
    providers: ProviderRegistryDep,
) -> AgentRead:
    agent = await agent_service.create_agent(
        session, principal, data, settings, registry, providers
    )
    return agent_service.to_read(agent)


@router.get("/{agent_id}")
async def get_agent(agent_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> AgentRead:
    agent = await agent_service.get_agent(session, agent_id, principal.workspace_id)
    return agent_service.to_read(agent)


@router.put("/{agent_id}")
async def update_agent(
    agent_id: uuid.UUID,
    data: AgentWrite,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
    providers: ProviderRegistryDep,
) -> AgentRead:
    agent = await agent_service.update_agent(
        session, principal, agent_id, data, settings, registry, providers
    )
    return agent_service.to_read(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await agent_service.delete_agent(session, principal, agent_id)
