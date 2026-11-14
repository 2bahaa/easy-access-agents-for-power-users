"""Helpers for driving and parsing the SSE run stream in integration tests."""

import json
from typing import Any

from httpx import AsyncClient


def parse_sse(body: str) -> list[dict[str, Any]]:
    """Parse an SSE body into [{'id', 'event', 'data'}]; comment-only frames are skipped."""
    events: list[dict[str, Any]] = []
    for frame in body.replace("\r\n", "\n").split("\n\n"):
        fields: dict[str, str] = {}
        data_lines: list[str] = []
        for line in frame.split("\n"):
            if not line or line.startswith(":"):
                continue
            key, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if key == "data":
                data_lines.append(value)
            else:
                fields[key] = value
        if data_lines:
            events.append({**fields, "data": json.loads("\n".join(data_lines))})
    return events


async def create_agent(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    payload = {"name": "Agent", "model": "tools:1b", "tools": [{"name": "calculator"}]}
    resp = await client.post("/api/agents", json=payload | overrides)
    assert resp.status_code == 201, resp.text
    agent: dict[str, Any] = resp.json()
    return agent


async def create_conversation(client: AsyncClient, agent_id: str) -> dict[str, Any]:
    resp = await client.post("/api/conversations", json={"agent_id": agent_id})
    assert resp.status_code == 201, resp.text
    conversation: dict[str, Any] = resp.json()
    return conversation


async def send_message(
    client: AsyncClient, conversation_id: str, content: str
) -> list[dict[str, Any]]:
    resp = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": content}
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    # Protocol invariants.
    assert [int(e["id"]) for e in events] == list(range(1, len(events) + 1))
    assert all(e["event"] == e["data"]["type"] for e in events)
    terminals = [
        e for e in events if e["event"] in {"run.completed", "run.failed", "run.cancelled"}
    ]
    assert len(terminals) == 1 and events[-1] is terminals[0]
    return events
