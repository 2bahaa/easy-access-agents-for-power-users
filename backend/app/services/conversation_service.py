"""Conversation management use cases."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, Conversation, Message, Run
from app.schemas.conversations import ConversationCreate
from app.services.errors import DomainValidationError, NotFoundError
from app.services.principal import Principal

DEFAULT_TITLE = "New conversation"


async def list_conversations(
    session: AsyncSession, workspace_id: uuid.UUID, agent_id: uuid.UUID | None = None
) -> Sequence[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.workspace_id == workspace_id)
        .order_by(Conversation.updated_at.desc())
    )
    if agent_id is not None:
        stmt = stmt.where(Conversation.agent_id == agent_id)
    return (await session.scalars(stmt)).all()


async def get_conversation(
    session: AsyncSession, conversation_id: uuid.UUID, workspace_id: uuid.UUID
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id, populate_existing=True)
    if conversation is None or conversation.workspace_id != workspace_id:
        raise NotFoundError(f"Conversation {conversation_id} not found")
    return conversation


async def list_messages(session: AsyncSession, conversation_id: uuid.UUID) -> Sequence[Message]:
    stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
    return (await session.scalars(stmt)).all()


async def list_runs(session: AsyncSession, conversation_id: uuid.UUID) -> Sequence[Run]:
    stmt = select(Run).where(Run.conversation_id == conversation_id).order_by(Run.started_at)
    return (await session.scalars(stmt)).all()


async def create_conversation(
    session: AsyncSession, principal: Principal, data: ConversationCreate
) -> Conversation:
    principal.require("editor")
    agent = await session.get(Agent, data.agent_id)
    if agent is None or agent.workspace_id != principal.workspace_id:
        raise DomainValidationError(f"Unknown agent id: {data.agent_id}")
    conversation = Conversation(
        workspace_id=principal.workspace_id,
        agent_id=data.agent_id,
        title=data.title or DEFAULT_TITLE,
    )
    session.add(conversation)
    await session.commit()
    return await get_conversation(session, conversation.id, principal.workspace_id)


async def delete_conversation(
    session: AsyncSession, principal: Principal, conversation_id: uuid.UUID
) -> None:
    principal.require("editor")
    conversation = await get_conversation(session, conversation_id, principal.workspace_id)
    await session.delete(conversation)  # messages/runs/events go via ON DELETE CASCADE
    await session.commit()
