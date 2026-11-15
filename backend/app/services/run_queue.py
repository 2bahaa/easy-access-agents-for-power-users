"""Durable run queue on Postgres (shared by the API and run workers).

Lifecycle:  queued ──claim──▶ running ──finish──▶ completed | failed | cancelled | …
                │                  └─ heartbeat lost ──reap──▶ failed (interrupted)
                └─ cancel ──▶ cancelled

* Claiming uses `FOR UPDATE SKIP LOCKED`, so any number of workers can poll safely.
* The API wakes workers with NOTIFY on `eaa_runs`; workers also poll as a fallback.
* Cancelling a running run sets `cancel_requested` and notifies; the owning worker stops it.
* Every state change that ends a run also writes its terminal event row and notifies the
  run's event channel in the same transaction, so subscribers always see the end.
"""

import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, RunEvent
from app.runtime.events import AgentEvent, agent_event_adapter
from app.services.pubsub import RUNS_CHANNEL, event_notification, notify, run_channel

INTERRUPTED_ERROR = "Interrupted by a server restart"


def _event_row(event: AgentEvent) -> RunEvent:
    payload = event.model_dump(mode="json", exclude={"run_id", "seq", "ts", "type"})
    return RunEvent(run_id=event.run_id, seq=event.seq, type=event.type, payload=payload)


async def write_events(session: AsyncSession, events: Sequence[AgentEvent]) -> None:
    """Persist (if persisted) and publish events in order, inside the caller's transaction."""
    for event in events:
        if event.persisted:
            session.add(_event_row(event))
    await session.flush()
    for event in events:
        await notify(
            session,
            run_channel(event.run_id),
            event_notification(event.model_dump_json(), event.seq, event.persisted),
        )


async def next_event_seq(session: AsyncSession, run_id: uuid.UUID) -> int:
    current = await session.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id))
    return (current or 0) + 1


async def wake_workers(session: AsyncSession) -> None:
    await notify(session, RUNS_CHANNEL, "queued")


async def claim_next(session: AsyncSession, worker_id: str) -> uuid.UUID | None:
    """Atomically move the oldest queued run to running for this worker."""
    oldest = (
        select(Run.id)
        .where(Run.status == "queued")
        .order_by(Run.started_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    run_id = await session.scalar(
        update(Run)
        .where(Run.id == oldest)
        .values(status="running", worker_id=worker_id, heartbeat_at=func.now())
        .returning(Run.id)
    )
    await session.commit()
    return run_id


async def heartbeat(session: AsyncSession, run_ids: Sequence[uuid.UUID]) -> None:
    if run_ids:
        await session.execute(
            update(Run)
            .where(Run.id.in_(run_ids), Run.status == "running")
            .values(heartbeat_at=func.now())
        )
        await session.commit()


async def _end_with_event(
    session: AsyncSession,
    run: Run,
    status: str,
    error: str | None,
    event_type: str,
    **payload: object,
) -> None:
    run.status = status
    run.error = error
    run.finished_at = func.now()
    seq = await next_event_seq(session, run.id)
    event = agent_event_adapter.validate_python(
        {"type": event_type, "run_id": run.id, "seq": seq, **payload}
    )
    await write_events(session, [event])


async def fail_run(session: AsyncSession, run: Run, message: str) -> None:
    """End a run as failed with a terminal event (caller commits)."""
    await _end_with_event(
        session, run, "failed", message, "run.failed", code="internal_error", message=message
    )


async def request_cancel(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """Cancel a queued run immediately, or ask the owning worker to stop a running one.
    Returns False if the run is not active."""
    run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
    if run is None or run.status not in ("queued", "running"):
        return False
    if run.status == "queued":
        await _end_with_event(session, run, "cancelled", None, "run.cancelled")
    else:
        run.cancel_requested = True
        await notify(session, RUNS_CHANNEL, f"cancel:{run_id}")
    await session.commit()
    return True


async def reap_stale_runs(session: AsyncSession, stale_after_s: float | None = None) -> int:
    """Fail running runs whose worker stopped sending heartbeats (crash/restart).
    `stale_after_s=None` treats every running run as stale (single-process startup)."""
    stmt = select(Run).where(Run.status == "running").with_for_update(skip_locked=True)
    if stale_after_s is not None:
        cutoff = func.now() - timedelta(seconds=stale_after_s)
        stmt = stmt.where((Run.heartbeat_at.is_(None)) | (Run.heartbeat_at < cutoff))
    runs = (await session.scalars(stmt)).all()
    for run in runs:
        await _end_with_event(
            session,
            run,
            "failed",
            INTERRUPTED_ERROR,
            "run.failed",
            code="internal_error",
            message=INTERRUPTED_ERROR,
        )
    await session.commit()
    return len(runs)
