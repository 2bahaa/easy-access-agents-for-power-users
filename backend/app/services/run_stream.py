"""Follow a run's events from any process: replay persisted events, then go live.

The LISTEN subscription starts *before* the replay query, so every event committed after
the replay is delivered as a notification; duplicates are dropped by `seq`. Token deltas
are never persisted, so a client that reconnects (`Last-Event-ID`) resumes from the next
persisted event — the final `message.completed` still carries the full text.
"""

import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RunEvent
from app.runtime.events import TERMINAL_TYPES, AgentEvent, agent_event_adapter
from app.services.pubsub import listen, run_channel

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def row_to_event(row: RunEvent) -> AgentEvent:
    return agent_event_adapter.validate_python(
        {
            **row.payload,
            "type": row.type,
            "run_id": row.run_id,
            "seq": row.seq,
            "ts": row.created_at,
        }
    )


async def _load(
    session_factory: SessionFactory, run_id: uuid.UUID, after_seq: int, only_seq: int | None = None
) -> list[AgentEvent]:
    stmt = select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
    if only_seq is not None:
        stmt = stmt.where(RunEvent.seq == only_seq)
    async with session_factory() as session:
        rows = (await session.scalars(stmt.order_by(RunEvent.seq))).all()
    return [row_to_event(r) for r in rows]


async def follow_run(
    session_factory: SessionFactory, dsn: str, run_id: uuid.UUID, after_seq: int = 0
) -> AsyncIterator[AgentEvent]:
    """Yield the run's events with seq > after_seq, ending after the terminal event."""
    async with listen(dsn, run_channel(run_id)) as notifications:
        last = after_seq
        for event in await _load(session_factory, run_id, after_seq):
            yield event
            last = event.seq
            if event.type in TERMINAL_TYPES:
                return
        while True:
            payload = json.loads(await notifications.get())
            if payload.get("skipped"):  # oversized transient event: nothing to deliver
                continue
            if payload.get("ref"):  # too large for NOTIFY: read the committed row
                events = await _load(session_factory, run_id, last, only_seq=int(payload["seq"]))
            else:
                events = [agent_event_adapter.validate_python(payload)]
            for event in events:
                if event.seq <= last:
                    continue
                yield event
                last = event.seq
                if event.type in TERMINAL_TYPES:
                    return
