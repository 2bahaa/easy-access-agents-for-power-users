"""Execution history and usage analytics, computed only from recorded runs and run events.

Nothing is estimated: token counts are the sums the providers reported (runs on providers
that report no usage contribute 0 and are counted in `runs_without_usage`), and durations
come from `started_at`/`finished_at`.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, Run, RunEvent, Workflow

TERMINAL = ("completed", "failed", "cancelled", "waiting_approval")


def _filtered(
    stmt: Any,  # any Select over Run
    workspace_id: uuid.UUID,
    *,
    kind: str | None = None,
    status: str | None = None,
    agent_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
) -> Any:
    stmt = stmt.where(Run.workspace_id == workspace_id)
    if kind:
        stmt = stmt.where(Run.kind == kind)
    if status:
        stmt = stmt.where(Run.status == status)
    if agent_id:
        stmt = stmt.where(Run.agent_id == agent_id)
    if workflow_id:
        stmt = stmt.where(Run.workflow_id == workflow_id)
    return stmt


async def list_runs(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    kind: str | None = None,
    status: str | None = None,
    agent_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Any], int]:
    """Runs newest first, with the agent/workflow name for display, plus the total count."""
    filters: dict[str, Any] = {
        "kind": kind,
        "status": status,
        "agent_id": agent_id,
        "workflow_id": workflow_id,
    }
    stmt = _filtered(
        select(Run, Agent.name.label("agent_name"), Workflow.name.label("workflow_name"))
        .outerjoin(Agent, Agent.id == Run.agent_id)
        .outerjoin(Workflow, Workflow.id == Run.workflow_id),
        workspace_id,
        **filters,
    )
    rows = (
        await session.execute(
            stmt.order_by(Run.started_at.desc(), Run.id).limit(limit).offset(offset)
        )
    ).all()
    total = await session.scalar(
        _filtered(select(func.count()).select_from(Run), workspace_id, **filters)
    )
    return rows, int(total or 0)


def _token(key: str) -> Any:
    return func.coalesce(cast(Run.usage[key].astext, Integer), 0)


async def summary(session: AsyncSession, workspace_id: uuid.UUID, days: int) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    in_window = [Run.workspace_id == workspace_id, Run.started_at >= since]
    duration = func.extract("epoch", Run.finished_at - Run.started_at) * 1000

    totals = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Run.tool_call_count), 0),
                func.coalesce(func.sum(_token("input_tokens")), 0),
                func.coalesce(func.sum(_token("output_tokens")), 0),
                func.count().filter(Run.usage["input_tokens"].astext.is_(None)),
                func.avg(duration).filter(Run.finished_at.is_not(None)),
                func.percentile_cont(0.95)
                .within_group(duration)
                .filter(Run.finished_at.is_not(None)),
            ).where(*in_window)
        )
    ).one()

    by_status = dict(
        (
            await session.execute(
                select(Run.status, func.count()).where(*in_window).group_by(Run.status)
            )
        ).all()
    )
    by_kind = dict(
        (
            await session.execute(
                select(Run.kind, func.count()).where(*in_window).group_by(Run.kind)
            )
        ).all()
    )

    day = func.date_trunc("day", Run.started_at).label("day")
    daily_rows = (
        await session.execute(
            select(
                day,
                func.count(),
                func.count().filter(Run.status == "failed"),
                func.coalesce(func.sum(_token("total_tokens")), 0),
            )
            .where(*in_window)
            .group_by(day)
            .order_by(day)
        )
    ).all()
    counts = {r[0].date().isoformat(): r for r in daily_rows}
    daily = []
    for i in range(days - 1, -1, -1):  # zero-filled so charts show quiet days honestly
        d = (datetime.now(UTC) - timedelta(days=i)).date().isoformat()
        r = counts.get(d)
        daily.append(
            {
                "date": d,
                "runs": int(r[1]) if r else 0,
                "failed": int(r[2]) if r else 0,
                "tokens": int(r[3]) if r else 0,
            }
        )

    top_agents = [
        {"agent_id": str(a), "name": n, "runs": int(c), "failed": int(f)}
        for a, n, c, f in (
            await session.execute(
                select(
                    Run.agent_id,
                    Agent.name,
                    func.count(),
                    func.count().filter(Run.status == "failed"),
                )
                .join(Agent, Agent.id == Run.agent_id)
                .where(*in_window)
                .group_by(Run.agent_id, Agent.name)
                .order_by(func.count().desc())
                .limit(5)
            )
        ).all()
    ]

    tool_name = RunEvent.payload["tool"].astext
    top_tools = [
        {"tool": t, "calls": int(c), "failed": int(f)}
        for t, c, f in (
            await session.execute(
                select(
                    tool_name,
                    func.count(),
                    func.count().filter(RunEvent.type == "tool.call.failed"),
                )
                .join(Run, Run.id == RunEvent.run_id)
                .where(*in_window, RunEvent.type.in_(("tool.call.completed", "tool.call.failed")))
                .group_by(tool_name)
                .order_by(func.count().desc())
                .limit(8)
            )
        ).all()
    ]

    runs, tool_calls, tokens_in, tokens_out, no_usage, avg_ms, p95_ms = totals
    finished = sum(by_status.get(s, 0) for s in ("completed", "failed"))
    return {
        "days": days,
        "runs": int(runs),
        "by_status": by_status,
        "by_kind": by_kind,
        "success_rate": (by_status.get("completed", 0) / finished) if finished else None,
        "tool_calls": int(tool_calls),
        "input_tokens": int(tokens_in),
        "output_tokens": int(tokens_out),
        "runs_without_usage": int(no_usage),
        "avg_duration_ms": round(avg_ms) if avg_ms is not None else None,
        "p95_duration_ms": round(p95_ms) if p95_ms is not None else None,
        "daily": daily,
        "top_agents": top_agents,
        "top_tools": top_tools,
    }
