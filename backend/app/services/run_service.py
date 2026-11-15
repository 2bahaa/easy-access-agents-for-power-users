"""Run use cases: queue a run, rebuild it for a worker, persist its results, cancel it."""

import logging
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    ACTIVE_RUN_STATUSES,
    Agent,
    Conversation,
    Message,
    Run,
    RunEvent,
    Workspace,
)
from app.runtime.executor import AgentRun
from app.runtime.types import (
    AgentConfig,
    RunRequest,
    RunResult,
    RuntimeCaps,
    SkillContent,
    ToolGrant,
)
from app.services import (
    agent_platform,
    agent_service,
    approval_service,
    audit_service,
    capability_service,
    conversation_service,
    run_queue,
)
from app.services.errors import ConflictError, NotFoundError
from app.services.principal import Principal
from app.services.provider_service import ProviderResolver
from app.tools.base import ToolContext
from app.tools.external import is_external
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
        connection_id=agent.connection_id,
        model=agent.model,
        model_params=agent.model_params,
        system_prompt=agent.system_prompt,
        skills=[
            SkillContent(
                slug=link.skill.slug, name=link.skill.name, content_md=link.skill.content_md
            )
            for link in agent.skill_links
        ],
        tools=[
            ToolGrant(name=t.tool_name, config=t.config, requires_approval=t.requires_approval)
            for t in agent.tool_links
        ],
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


def _with_answered_tool_calls(
    messages: list[BaseMessage], awaiting: frozenset[str] = frozenset()
) -> list[BaseMessage]:
    """Add error ToolMessages for tool calls that never got a result (cancel/timeout),
    so the stored history stays valid for the next turn. Calls awaiting approval are left
    open: the continuation run answers them."""
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)} | set(awaiting)
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


async def _next_seq(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    current = await session.scalar(
        select(func.max(Message.seq)).where(Message.conversation_id == conversation_id)
    )
    return (current or 0) + 1


async def apply_result(
    session: AsyncSession, run: Run, result: RunResult, approval_ttl_s: float = 86_400
) -> None:
    """Write a finished run's messages and final status (caller commits, together with
    the terminal event, so subscribers never see the end before the messages)."""
    next_seq = await _next_seq(session, run.conversation_id)
    awaiting = frozenset(str(p["call_id"]) for p in result.pending_approvals)
    for offset, msg in enumerate(_with_answered_tool_calls(result.new_messages, awaiting)):
        session.add(_to_row(msg, run.conversation_id, run.id, next_seq + offset))
    if result.status == "waiting_approval":
        approval_service.create_requests(session, run, result.pending_approvals, approval_ttl_s)
    run.status = result.status if result.status != "running" else "failed"
    run.tool_call_count = result.tool_call_count
    run.usage = result.usage
    run.error = result.error
    run.finished_at = func.now()
    await session.execute(
        update(Conversation)
        .where(Conversation.id == run.conversation_id)
        .values(updated_at=func.now())
    )


# ---- use cases ----------------------------------------------------------------------


async def active_run_id(session: AsyncSession, conversation_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(
        select(Run.id).where(
            Run.conversation_id == conversation_id, Run.status.in_(ACTIVE_RUN_STATUSES)
        )
    )


async def start_run(
    session: AsyncSession,
    principal: Principal,
    conversation_id: uuid.UUID,
    content: str,
    *,
    resolver: ProviderResolver,
) -> Run:
    """Validate, persist the user message + a queued run, and wake a worker.
    Raises domain errors (403/404/409/422) before anything streams."""
    principal.require("editor")
    ws = principal.workspace_id
    conversation = await conversation_service.get_conversation(session, conversation_id, ws)
    if await active_run_id(session, conversation_id) is not None:
        raise ConflictError("A run is already in progress for this conversation")

    agent = await agent_service.get_agent(session, conversation.agent_id, ws)
    config, agent_version = await agent_platform.runtime_config_for_chat(
        session, agent, playground=conversation.kind == "playground"
    )
    # Workspace approval policies apply to every run (published or draft).
    config = await approval_service.apply_policies(session, ws, agent.id, config)
    await resolver.resolve(session, ws, config.provider, config.connection_id)  # 404/422 early

    user_message = Message(
        conversation_id=conversation_id,
        seq=await _next_seq(session, conversation_id),
        role="user",
        content=content,
    )
    run = Run(
        workspace_id=ws,
        conversation_id=conversation_id,
        agent_id=agent.id,
        status="queued",
        agent_version=agent_version,
        agent_snapshot=config.model_dump(mode="json"),
    )
    session.add_all([user_message, run])
    try:
        await session.flush()
    except IntegrityError:  # another request queued a run concurrently
        await session.rollback()
        raise ConflictError("A run is already in progress for this conversation") from None
    user_message.run_id = run.id
    if conversation.title == conversation_service.DEFAULT_TITLE:
        conversation.title = content.strip().splitlines()[0][:TITLE_MAX] or conversation.title
    conversation.updated_at = func.now()
    await run_queue.wake_workers(session)
    await session.commit()
    return run


async def prepare_agent_run(
    session: AsyncSession,
    run: Run,
    *,
    settings: Settings,
    resolver: ProviderResolver,
    tools: ToolRegistry,
) -> AgentRun:
    """Rebuild a claimed run's runtime inputs from the database (worker side)."""
    config = AgentConfig.model_validate(run.agent_snapshot)
    provider = await resolver.resolve(
        session, run.workspace_id, config.provider, config.connection_id
    )
    workspace = await session.get(Workspace, run.workspace_id)
    if workspace is None:
        raise NotFoundError(f"Workspace of run {run.id} not found")
    messages = await conversation_service.list_messages(session, run.conversation_id)
    user_message_id = next(
        (m.id for m in messages if m.run_id == run.id and m.role == "user"), None
    )
    external = [t.name for t in config.tools if is_external(t.name)]
    if external:  # only the agent's granted, still-enabled external tools (secrets in memory)
        tools = tools.extended(
            await capability_service.external_tools(
                session, run.workspace_id, settings, resolver.secrets, names=external
            )
        )
    resume = await approval_service.decisions_for(session, run.resume_of) if run.resume_of else None
    return AgentRun(
        RunRequest(
            run_id=run.id,
            config=config,
            history=to_langchain(messages),
            conversation_id=run.conversation_id,
            user_message_id=user_message_id,
            resume=resume,
        ),
        provider,
        tools,
        RuntimeCaps(
            max_tool_calls=settings.max_tool_calls_cap,
            run_timeout_s=settings.run_timeout_cap_s,
            tool_timeout_s=settings.tool_timeout_s,
        ),
        ToolContext(workspace_dir=workspace_files_dir(settings, workspace)),
    )


def workspace_files_dir(settings: Settings, workspace: Workspace) -> Path:
    """Each workspace's file sandbox is its own folder under WORKSPACE_DIR (tenant isolation)."""
    return settings.workspace_dir / workspace.slug


async def get_run(session: AsyncSession, run_id: uuid.UUID, workspace_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id, populate_existing=True)
    if run is None or run.workspace_id != workspace_id:
        raise NotFoundError(f"Run {run_id} not found")
    return run


async def list_run_events(
    session: AsyncSession, run_id: uuid.UUID, workspace_id: uuid.UUID, after_seq: int = 0
) -> Sequence[RunEvent]:
    await get_run(session, run_id, workspace_id)
    stmt = (
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
        .order_by(RunEvent.seq)
    )
    return (await session.scalars(stmt)).all()


async def cancel_run(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> None:
    principal.require("editor")
    run = await get_run(session, run_id, principal.workspace_id)
    if await run_queue.request_cancel(session, run_id):
        audit_service.record(
            session, "run.cancelled", principal=principal, target_type="run", target_id=run_id
        )
        await session.commit()
        return
    raise ConflictError(f"Run is not active (status: {run.status})")


async def mark_interrupted_runs(session: AsyncSession) -> int:
    """Fail every run left 'running' (single-process startup / tests).
    Multi-process deployments rely on heartbeat-based reaping in the worker instead."""
    return await run_queue.reap_stale_runs(session, stale_after_s=None)
