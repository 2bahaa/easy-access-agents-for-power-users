"""Serialize a run's events as Server-Sent Events (docs/API_DESIGN.md §4).

Frame:  id: <seq> / event: <type> / data: <event JSON>.  A `: ping` comment is sent when
idle for PING_INTERVAL_S. If the client goes away before the terminal event, the run is
cancelled (synchronously, so this is safe inside a cancelled request).
"""

import asyncio
from collections.abc import AsyncIterator, Callable

from fastapi.sse import KEEPALIVE_COMMENT, format_sse_event

from app.runtime.events import AgentEvent

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
