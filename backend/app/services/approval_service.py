"""Human-in-the-loop approvals.

Flow: the runtime holds tool calls that require approval and ends the run as
`waiting_approval`; the worker stores one `approval_requests` row per held call. Users decide
them (approve — optionally with edited arguments — or reject); requests not decided before
`expires_at` expire (treated as rejected). When every request of a run is decided, the run
becomes `resumed` and a continuation run is queued: it executes the approved calls through
the normal ToolNode checks, refuses the rejected ones, and lets the agent continue.

The model can never approve anything: decisions only come from authenticated users with the
editor role, and are audited.
"""

import fnmatch
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApprovalPolicy, ApprovalRequest, Run
from app.runtime.types import AgentConfig, ResumeDecisions
from app.services import audit_service, run_queue
from app.services.errors import ConflictError, DomainValidationError, NotFoundError
from app.services.principal import Principal

REJECTED_MESSAGE = "A human reviewer rejected this action"
EXPIRED_MESSAGE = "The approval request expired before anyone decided it"


# ---- policies ---------------------------------------------------------------------------


async def apply_policies(
    session: AsyncSession, workspace_id: uuid.UUID, agent_id: uuid.UUID, config: AgentConfig
) -> AgentConfig:
    """Mark granted tools that match a workspace policy as requiring approval."""
    policies = (
        await session.scalars(
            select(ApprovalPolicy).where(
                ApprovalPolicy.workspace_id == workspace_id,
                (ApprovalPolicy.agent_id.is_(None)) | (ApprovalPolicy.agent_id == agent_id),
            )
        )
    ).all()
    if not policies:
        return config
    tools = [
        g.model_copy(
            update={
                "requires_approval": g.requires_approval
                or any(fnmatch.fnmatchcase(g.name, p.tool_pattern) for p in policies)
            }
        )
        for g in config.tools
    ]
    return config.model_copy(update={"tools": tools})


async def list_policies(session: AsyncSession, principal: Principal) -> Sequence[ApprovalPolicy]:
    stmt = select(ApprovalPolicy).where(ApprovalPolicy.workspace_id == principal.workspace_id)
    return (await session.scalars(stmt.order_by(ApprovalPolicy.created_at))).all()


async def create_policy(
    session: AsyncSession, principal: Principal, tool_pattern: str, agent_id: uuid.UUID | None
) -> ApprovalPolicy:
    principal.require("admin")
    if agent_id is not None:
        from app.services.agent_service import get_agent

        try:
            await get_agent(session, agent_id, principal.workspace_id)
        except NotFoundError:
            raise DomainValidationError(f"Unknown agent id: {agent_id}") from None
    policy = ApprovalPolicy(
        workspace_id=principal.workspace_id,
        agent_id=agent_id,
        tool_pattern=tool_pattern,
        created_by=principal.user_id,
    )
    session.add(policy)
    await session.flush()
    audit_service.record(
        session,
        "approval.policy_created",
        principal=principal,
        target_type="approval_policy",
        target_id=policy.id,
        pattern=tool_pattern,
        agent=str(agent_id) if agent_id else None,
    )
    await session.commit()
    return policy


async def delete_policy(session: AsyncSession, principal: Principal, policy_id: uuid.UUID) -> None:
    principal.require("admin")
    policy = await session.get(ApprovalPolicy, policy_id)
    if policy is None or policy.workspace_id != principal.workspace_id:
        raise NotFoundError("Approval policy not found")
    await session.delete(policy)
    audit_service.record(
        session,
        "approval.policy_deleted",
        principal=principal,
        target_type="approval_policy",
        target_id=policy_id,
    )
    await session.commit()


# ---- requests ---------------------------------------------------------------------------


def create_requests(
    session: AsyncSession, run: Run, pending: list[dict[str, Any]], ttl_s: float
) -> None:
    """Called by the worker in the transaction that ends the run as waiting_approval."""
    expires = datetime.now(UTC) + timedelta(seconds=ttl_s)
    for p in pending:
        session.add(
            ApprovalRequest(
                workspace_id=run.workspace_id,
                run_id=run.id,
                conversation_id=run.conversation_id,
                agent_id=run.agent_id,
                call_id=str(p["call_id"]),
                tool_name=str(p["tool"]),
                args=dict(p.get("args") or {}),
                expires_at=expires,
            )
        )


async def list_requests(
    session: AsyncSession,
    principal: Principal,
    *,
    status: str | None = "pending",
    run_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> Sequence[ApprovalRequest]:
    stmt = select(ApprovalRequest).where(ApprovalRequest.workspace_id == principal.workspace_id)
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    if run_id:
        stmt = stmt.where(ApprovalRequest.run_id == run_id)
    if conversation_id:
        stmt = stmt.where(ApprovalRequest.conversation_id == conversation_id)
    return (
        await session.scalars(stmt.order_by(ApprovalRequest.created_at.desc()).limit(200))
    ).all()


async def _maybe_resume(session: AsyncSession, run_id: uuid.UUID) -> Run | None:
    """If no request of the run is pending any more, queue its continuation (caller commits)."""
    pending = await session.scalar(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(ApprovalRequest.run_id == run_id, ApprovalRequest.status == "pending")
    )
    if pending:
        return None
    original = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
    if original is None or original.status != "waiting_approval":
        return None
    original.status = "resumed"
    original.finished_at = func.now()
    await session.flush()  # leave the active set before the continuation enters it
    continuation = Run(
        workspace_id=original.workspace_id,
        kind=original.kind,
        conversation_id=original.conversation_id,
        agent_id=original.agent_id,
        workflow_id=original.workflow_id,
        inputs=original.inputs,
        status="queued",
        agent_version=original.agent_version,
        agent_snapshot=original.agent_snapshot,
        resume_of=original.id,
    )
    session.add(continuation)
    await session.flush()
    await run_queue.wake_workers(session)
    return continuation


async def decide(
    session: AsyncSession,
    principal: Principal,
    request_id: uuid.UUID,
    approve: bool,
    *,
    edited_args: dict[str, Any] | None = None,
    note: str = "",
) -> tuple[ApprovalRequest, Run | None]:
    principal.require("editor")
    req = await session.scalar(
        select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update()
    )
    if req is None or req.workspace_id != principal.workspace_id:
        raise NotFoundError("Approval request not found")
    if req.status != "pending":
        raise ConflictError(f"This request was already {req.status}")
    if req.expires_at <= datetime.now(UTC):
        raise ConflictError("This request has expired")
    req.status = "approved" if approve else "rejected"
    req.edited_args = edited_args if approve and edited_args is not None else None
    req.decided_by = principal.user_id
    req.decided_at = func.now()
    req.note = note
    audit_service.record(
        session,
        "approval.approved" if approve else "approval.rejected",
        principal=principal,
        target_type="approval",
        target_id=req.id,
        tool=req.tool_name,
        run=str(req.run_id),
        edited=edited_args is not None,
    )
    await session.flush()
    continuation = await _maybe_resume(session, req.run_id)
    await session.commit()
    await session.refresh(req)  # load server-side timestamps (decided_at)
    return req, continuation


async def expire_due(session: AsyncSession) -> int:
    """Expire overdue requests and resume their runs (worker maintenance)."""
    due = (
        await session.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == "pending", ApprovalRequest.expires_at <= func.now())
            .with_for_update(skip_locked=True)
        )
    ).all()
    run_ids = {r.run_id for r in due}
    for r in due:
        r.status = "expired"
        r.decided_at = func.now()
    await session.flush()
    for run_id in run_ids:
        await _maybe_resume(session, run_id)
    await session.commit()
    return len(due)


async def cancel_for_run(session: AsyncSession, run_id: uuid.UUID) -> None:
    await session.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.run_id == run_id, ApprovalRequest.status == "pending")
        .values(status="cancelled", decided_at=func.now())
    )


async def decisions_for(session: AsyncSession, resumed_run_id: uuid.UUID) -> ResumeDecisions:
    rows = (
        await session.scalars(
            select(ApprovalRequest).where(ApprovalRequest.run_id == resumed_run_id)
        )
    ).all()
    approved: dict[str, dict[str, Any]] = {}
    rejected: dict[str, str] = {}
    for r in rows:
        if r.status == "approved":
            approved[r.call_id] = r.edited_args if r.edited_args is not None else r.args
        elif r.status == "expired":
            rejected[r.call_id] = EXPIRED_MESSAGE
        else:
            reason = REJECTED_MESSAGE + (f": {r.note}" if r.note else "")
            rejected[r.call_id] = reason
    return ResumeDecisions(approved=approved, rejected=rejected)
