import asyncio
import contextlib
import uuid

from app.api.sse import format_event, sse_stream
from app.runtime.events import AgentEvent, MessageDelta, RunCompleted
from tests.sse_helpers import parse_sse

RUN_ID = uuid.uuid4()


def test_format_event_frame() -> None:
    frame = format_event(MessageDelta(run_id=RUN_ID, seq=3, text="hi\nthere")).decode()
    assert "event: message.delta\n" in frame
    assert "id: 3\n" in frame and frame.endswith("\n\n")
    (parsed,) = parse_sse(frame)
    assert parsed["event"] == "message.delta" and parsed["id"] == "3"
    assert parsed["data"]["text"] == "hi\nthere"


async def test_stream_until_end_marker_does_not_cancel() -> None:
    queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
    queue.put_nowait(MessageDelta(run_id=RUN_ID, seq=1, text="a"))
    queue.put_nowait(RunCompleted(run_id=RUN_ID, seq=2, tool_call_count=0, usage={}, duration_ms=1))
    queue.put_nowait(None)
    cancelled: list[bool] = []
    chunks = [c async for c in sse_stream(queue, on_disconnect=lambda: cancelled.append(True))]
    assert [e["event"] for e in parse_sse(b"".join(chunks).decode())] == [
        "message.delta",
        "run.completed",
    ]
    assert cancelled == []


async def test_idle_stream_sends_keepalive() -> None:
    queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
    stream = sse_stream(queue, on_disconnect=lambda: None, ping_interval_s=0.01)
    assert await anext(stream) == b": ping\n\n"
    queue.put_nowait(None)
    assert [c async for c in stream] == []


async def test_client_disconnect_cancels_run() -> None:
    queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
    queue.put_nowait(MessageDelta(run_id=RUN_ID, seq=1, text="a"))
    cancelled: list[bool] = []
    async with contextlib.aclosing(
        sse_stream(queue, on_disconnect=lambda: cancelled.append(True))
    ) as stream:
        await anext(stream)  # client reads one event, then goes away
    assert cancelled == [True]
