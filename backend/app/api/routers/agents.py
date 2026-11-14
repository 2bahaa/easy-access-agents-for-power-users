import uuid

from fastapi import APIRouter, status

from app.api.deps import SessionDep, SettingsDep, ToolRegistryDep
from app.schemas.agents import AgentRead, AgentSummary, AgentWrite
from app.services import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents(session: SessionDep) -> list[AgentSummary]:
    return [AgentSummary.model_validate(a) for a in await agent_service.list_agents(session)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    data: AgentWrite, session: SessionDep, settings: SettingsDep, registry: ToolRegistryDep
) -> AgentRead:
    agent = await agent_service.create_agent(session, data, settings, registry)
    return agent_service.to_read(agent)


@router.get("/{agent_id}")
async def get_agent(agent_id: uuid.UUID, session: SessionDep) -> AgentRead:
    return agent_service.to_read(await agent_service.get_agent(session, agent_id))


@router.put("/{agent_id}")
async def update_agent(
    agent_id: uuid.UUID,
    data: AgentWrite,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
) -> AgentRead:
    agent = await agent_service.update_agent(session, agent_id, data, settings, registry)
    return agent_service.to_read(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: uuid.UUID, session: SessionDep) -> None:
    await agent_service.delete_agent(session, agent_id)
