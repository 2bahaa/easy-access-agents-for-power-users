"""Postgres LISTEN/NOTIFY helpers: the only cross-process channel between API and workers.

NOTIFY is transactional: a notification sent inside a transaction is delivered only when
that transaction commits, in commit order. Event rows and their notifications are written
in the same transaction, so a subscriber that gets a notification can always read the row.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Worker control channel. Payloads: "queued" | "cancel:<run uuid>".
RUNS_CHANNEL = "eaa_runs"
# NOTIFY payloads must stay below 8000 bytes; larger events are sent as a reference.
MAX_NOTIFY_BYTES = 7500


def run_channel(run_id: uuid.UUID) -> str:
    """Per-run event channel (identifier < 63 chars, no quoting needed)."""
    return f"eaa_run_{run_id.hex}"


async def notify(session: AsyncSession, channel: str, payload: str) -> None:
    """Queue a notification in the session's transaction (sent on commit)."""
    await session.execute(select(func.pg_notify(channel, payload)))


def event_notification(event_json: str, seq: int, persisted: bool) -> str:
    """Payload for a run event: the event itself, or a reference if it is too large.
    Persisted events are referenced (their row is committed with the notify). An oversized
    transient event (token delta; the runtime already splits them) is marked skipped: the
    following message.completed carries the full text."""
    if len(event_json.encode()) <= MAX_NOTIFY_BYTES:
        return event_json
    if persisted:
        return json.dumps({"ref": True, "seq": seq})
    return json.dumps({"skipped": True, "seq": seq})


@contextlib.asynccontextmanager
async def listen(dsn: str, *channels: str) -> AsyncIterator["asyncio.Queue[str]"]:
    """Subscribe to channels on a dedicated connection; yields a queue of payloads.
    The subscription is active once the context is entered."""
    queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(_conn: Any, _pid: int, _channel: str, payload: str) -> None:
        queue.put_nowait(payload)

    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        for channel in channels:
            await conn.add_listener(channel, _on_notify)
        yield queue
    finally:
        with contextlib.suppress(Exception):
            await asyncio.shield(conn.close(timeout=2))
