"""Run orchestration: prepare a run from DB state, start it, persist its results."""

import logging
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Agent, Conversation, Message, Run, RunEvent
from app.runtime.events import AgentEvent
from app.runtime.executor import AgentRun
from app.runtime.providers.registry import ProviderRegistry, UnknownProviderError
from app.runtime.types import (
    AgentConfig,
    RunRequest,
    RunResult,
    RuntimeCaps,
    SkillContent,
    ToolGrant,
)
from app.services import agent_service, conversation_service
from app.services.errors import ConflictError, DomainValidationError, NotFoundError
from app.services.run_manager import ActiveRun, RunManager
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

TITLE_MAX = 60
UNFINISHED_TOOL_CALL = "Error: the run ended before this tool call completed."


# ---- mapping ------------------------------------------------------------------------


def to_agent_config(agent: Agent) -> AgentConfig:
    return AgentConfig(
        agent_id=agent.id,
        name=agent.name,
        provider=agent.provider,
        model=agent.model,
        model_params=agent.model_params,
        system_prompt=agent.system_prompt,
        skills=[
            SkillContent(
                slug=link.skill.slug, name=link.skill.name, content_md=link.skill.content_md
            )
            for link in agent.skill_links
        ],
        tools=[ToolGrant(name=t.tool_name, config=t.config) for t in agent.tool_links],
        max_tool_calls=agent.max_tool_calls,
        run_timeout_s=agent.run_timeout_s,
    )


def to_langchain(messages: Sequence[Message]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in messages:
        if m.role == "user":
            out.append(HumanMessage(m.content, id=str(m.id)))
        elif m.role == "assistant":
            out.append(AIMessage(m.content, tool_calls=m.tool_calls or [], id=str(m.id)))
        elif m.role == "tool":
            out.append(
                ToolMessage(
                    m.content, tool_call_id=m.tool_call_id or "", name=m.tool_name, id=str(m.id)
                )
            )
    return out


def _uuid(value: str | None) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return uuid.uuid4()


def _with_answered_tool_calls(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Add error ToolMessages for tool calls that never got a result (cancel/timeout),
    so the stored history stays valid for the next turn."""
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    out = list(messages)
    for m in messages:
        if isinstance(m, AIMessage):
            for call in m.tool_calls:
                call_id = call.get("id")
                if call_id and call_id not in answered:
                    out.append(
                        ToolMessage(
                            UNFINISHED_TOOL_CALL,
                            tool_call_id=call_id,
                            name=call["name"],
                            status="error",
                        )
                    )
                    answered.add(call_id)
    return out


def _to_row(msg: BaseMessage, conversation_id: uuid.UUID, run_id: uuid.UUID, seq: int) -> Message:
    common: dict[str, Any] = {
        "id": _uuid(msg.id),
        "conversation_id": conversation_id,
        "run_id": run_id,
        "seq": seq,
        "content": msg.text,
    }
    if isinstance(msg, AIMessage):
        calls = [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in msg.tool_calls]
        return Message(role="assistant", tool_calls=calls or None, **common)
    if isinstance(msg, ToolMessage):
        return Message(role="tool", tool_call_id=msg.tool_call_id, tool_name=msg.name, **common)
    raise ValueError(f"Unexpected message type from runtime: {type(msg).__name__}")


# ---- persistence --------------------------------------------------------------------


class DbRunRecorder:
    """Writes a run's events and final result. Uses its own sessions because it runs in
    the background run task, after the request that started the run has finished."""

    def __init__(
        self, session_factory: SessionFactory, run_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> None:
        self.session_factory = session_factory
        self.run_id = run_id
        self.conversation_id = conversation_id

    async def record_event(self, event: AgentEvent) -> None:
        payload = event.model_dump(mode="json", exclude={"run_id", "seq", "ts", "type"})
        async with self.session_factory() as session:
            session.add(
                RunEvent(run_id=self.run_id, seq=event.seq, type=event.type, payload=payload)
            )
            await session.commit()

    async def finish(self, result: RunResult) -> None:
        async with self.session_factory() as session:
            run = await session.get(Run, self.run_id)
            if run is None:  # conversation/agent deleted mid-run
                return
            next_seq = await _next_seq(session, self.conversation_id)
            for offset, msg in enumerate(_with_answered_tool_calls(result.new_messages)):
                session.add(_to_row(msg, self.conversation_id, self.run_id, next_seq + offset))
            run.status = result.status if result.status != "running" else "failed"
            run.tool_call_count = result.tool_call_count
            run.usage = result.usage
            run.error = result.error
            run.finished_at = func.now()
            await session.execute(
                update(Conversation)
                .where(Conversation.id == self.conversation_id)
                .values(updated_at=func.now())
            )
            await session.commit()


async def _next_seq(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    current = await session.scalar(
        select(func.max(Message.seq)).where(Message.conversation_id == conversation_id)
    )
    return (current or 0) + 1


# ---- use cases ----------------------------------------------------------------------


async def start_run(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    content: str,
    *,
    settings: Settings,
    providers: ProviderRegistry,
    tools: ToolRegistry,
    manager: RunManager,
    session_factory: SessionFactory,
) -> ActiveRun:
    """Validate, persist the user message + run row, and start the run in the background.
    Raises domain errors (404/409/422) before anything streams."""
    # In-memory check first: a busy conversation is rejected without touching the DB.
    if manager.has_active_run(conversation_id):
        raise ConflictError("A run is already in progress for this conversation")
    conversation = await conversation_service.get_conversation(session, conversation_id)

    agent = await agent_service.get_agent(session, conversation.agent_id)
    config = to_agent_config(agent)
    try:
        provider = providers.get(config.provider)
    except UnknownProviderError:
        raise DomainValidationError(f"Unknown provider: '{config.provider}'") from None

    history = to_langchain(await conversation_service.list_messages(session, conversation_id))
    user_message = Message(
        conversation_id=conversation_id,
        seq=await _next_seq(session, conversation_id),
        role="user",
        content=content,
    )
    run = Run(
        conversation_id=conversation_id,
        agent_id=agent.id,
        status="running",
        agent_snapshot=config.model_dump(mode="json"),
    )
    session.add_all([user_message, run])
    await session.flush()
    user_message.run_id = run.id
    if conversation.title == conversation_service.DEFAULT_TITLE:
        conversation.title = content.strip().splitlines()[0][:TITLE_MAX] or conversation.title
    conversation.updated_at = func.now()
    await session.commit()

    agent_run = AgentRun(
        RunRequest(
            run_id=run.id,
            config=config,
            history=[*history, HumanMessage(content, id=str(user_message.id))],
            conversation_id=conversation_id,
            user_message_id=user_message.id,
        ),
        provider,
        tools,
        RuntimeCaps(
            max_tool_calls=settings.max_tool_calls_cap,
            run_timeout_s=settings.run_timeout_cap_s,
            tool_timeout_s=settings.tool_timeout_s,
        ),
        ToolContext(workspace_dir=settings.workspace_dir),
    )
    recorder = DbRunRecorder(session_factory, run.id, conversation_id)
    return manager.start(run.id, conversation_id, agent_run, recorder)


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id, populate_existing=True)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")
    return run


async def list_run_events(session: AsyncSession, run_id: uuid.UUID) -> Sequence[RunEvent]:
    await get_run(session, run_id)
    stmt = select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
    return (await session.scalars(stmt)).all()


async def cancel_run(session: AsyncSession, run_id: uuid.UUID, manager: RunManager) -> None:
    if manager.cancel(run_id):  # no DB access while the run task may be writing
        return
    run = await get_run(session, run_id)
    raise ConflictError(f"Run is not active (status: {run.status})")


async def mark_interrupted_runs(session: AsyncSession) -> int:
    """Runs left 'running' by a previous process can never finish: mark them failed."""
    result = await session.execute(
        update(Run)
        .where(Run.status == "running")
        .values(status="failed", error="Interrupted by a server restart", finished_at=func.now())
    )
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)
