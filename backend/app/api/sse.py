"""Serialize a run's events as Server-Sent Events (docs/API_DESIGN.md §4).

Frame:  id: <seq> / event: <type> / data: <event JSON>.  A `: ping` comment is sent when
idle for PING_INTERVAL_S. If the client goes away before the terminal event,
`on_disconnect` runs (synchronously, so this is safe inside a cancelled request). Runs are
durable: disconnecting only stops *following* the run; it keeps executing in its worker.
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Callable

from fastapi.sse import KEEPALIVE_COMMENT, format_sse_event

from app.runtime.events import AgentEvent
from app.services.run_stream import SessionFactory, follow_run

PING_INTERVAL_S = 15.0


def format_event(event: AgentEvent) -> bytes:
    return format_sse_event(data_str=event.model_dump_json(), event=event.type, id=str(event.seq))


async def sse_stream(
    queue: asyncio.Queue[AgentEvent | None],
    on_disconnect: Callable[[], object],
    ping_interval_s: float = PING_INTERVAL_S,
) -> AsyncIterator[bytes]:
    finished = False
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=ping_interval_s)
            except TimeoutError:
                yield KEEPALIVE_COMMENT
                continue
            if event is None:
                finished = True
                return
            yield format_event(event)
    finally:
        if not finished:
            on_disconnect()


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def follow_run_sse(
    session_factory: SessionFactory, dsn: str, run_id: uuid.UUID, after_seq: int = 0
) -> AsyncIterator[bytes]:
    """SSE body that follows a run (replay + live) until its terminal event."""
    queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for event in follow_run(session_factory, dsn, run_id, after_seq):
                queue.put_nowait(event)
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(pump(), name=f"follow-{run_id}")

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in sse_stream(queue, on_disconnect=task.cancel):
                yield chunk
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    return body()
