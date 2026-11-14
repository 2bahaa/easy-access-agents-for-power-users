"""End-to-end over HTTP: POST message -> SSE stream -> persisted messages, runs, events."""

import asyncio
import uuid
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from langchain_core.messages import ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run
from app.main import create_app
from app.services.run_service import mark_interrupted_runs
from tests.fakes import FakeProvider, reply, tool_call
from tests.sse_helpers import create_agent, create_conversation, parse_sse, send_message


def types(events: list[dict[str, Any]]) -> list[str]:
    return [e["event"] for e in events]


async def test_calculator_run_streams_and_persists(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    fake_provider.model.responses = [
        reply("", tool_call("calculator", {"expression": "17.5 * 23 + 4"}, "c1")),
        reply("The answer is 406.5."),
    ]
    agent = await create_agent(client)
    conv = await create_conversation(client, agent["id"])

    events = await send_message(client, conv["id"], "What is 17.5 * 23 + 4?")

    assert types(events)[:3] == ["run.started", "tool.call.started", "tool.call.completed"]
    started = events[0]["data"]
    assert started["conversation_id"] == conv["id"] and started["agent_id"] == agent["id"]
    assert "".join(e["data"]["text"] for e in events if e["event"] == "message.delta") == (
        "The answer is 406.5."
    )
    assert events[-1]["event"] == "run.completed"
    run_id = started["run_id"]

    detail = (await client.get(f"/api/conversations/{conv['id']}")).json()
    assert detail["title"] == "What is 17.5 * 23 + 4?"
    messages = detail["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "assistant"]
    assert [m["seq"] for m in messages] == [1, 2, 3, 4]
    assert messages[0]["id"] == started["user_message_id"]
    assert all(m["run_id"] == run_id for m in messages)
    assert messages[1]["tool_calls"] == [
        {"id": "c1", "name": "calculator", "args": {"expression": "17.5 * 23 + 4"}}
    ]
    assert (messages[2]["tool_call_id"], messages[2]["tool_name"], messages[2]["content"]) == (
        "c1",
        "calculator",
        "406.5",
    )
    final = next(e for e in events if e["event"] == "message.completed")["data"]
    assert messages[3]["id"] == final["message_id"]
    assert messages[3]["content"] == "The answer is 406.5."

    run = (await client.get(f"/api/runs/{run_id}")).json()
    assert run["status"] == "completed" and run["finished_at"] is not None
    assert run["tool_call_count"] == 1 and run["usage"]["total_tokens"] == 30
    assert [r["id"] for r in detail["runs"]] == [run_id]

    timeline = (await client.get(f"/api/runs/{run_id}/events")).json()
    assert [e["type"] for e in timeline] == [
        t for t in types(events) if t not in {"message.delta", "reasoning.delta"}
    ]
    assert timeline[1]["payload"] == {
        "call_id": "c1",
        "tool": "calculator",
        "args": {"expression": "17.5 * 23 + 4"},
    }


async def test_history_is_sent_on_next_turn(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    fake_provider.model.responses = [
        reply("", tool_call("calculator", {"expression": "2+2"}, "c1")),
        reply("It is 4."),
        reply("You asked about 2+2."),
    ]
    agent = await create_agent(client, system_prompt="Be exact.")
    conv = await create_conversation(client, agent["id"])
    await send_message(client, conv["id"], "What is 2+2?")
    await send_message(client, conv["id"], "What did I ask?")

    third_prompt = fake_provider.model.prompts[2]
    assert [type(m).__name__ for m in third_prompt] == [
        "SystemMessage",
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
        "AIMessage",
        "HumanMessage",
    ]
    assert third_prompt[-1].content == "What did I ask?"
    assert isinstance(third_prompt[3], ToolMessage) and third_prompt[3].tool_call_id == "c1"

    detail = (await client.get(f"/api/conversations/{conv['id']}")).json()
    assert [m["seq"] for m in detail["messages"]] == [1, 2, 3, 4, 5, 6]
    assert len(detail["runs"]) == 2


async def test_failed_run_is_persisted(client: AsyncClient, fake_provider: FakeProvider) -> None:
    fake_provider.missing_models.add("gone:1b")
    agent = await create_agent(client, model="gone:1b")  # save allowed: capability unknown
    conv = await create_conversation(client, agent["id"])

    events = await send_message(client, conv["id"], "hello")
    assert types(events) == ["run.started", "run.failed"]
    assert events[-1]["data"]["code"] == "provider_error"

    detail = (await client.get(f"/api/conversations/{conv['id']}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user"]
    (run,) = detail["runs"]
    assert run["status"] == "failed" and "not available" in run["error"]


async def test_limit_exceeded_keeps_history_valid(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    fake_provider.model.responses = [
        reply(
            "",
            tool_call("calculator", {"expression": "1+1"}, "a"),
            tool_call("calculator", {"expression": "2+2"}, "b"),
        ),
        reply("Second turn works."),
    ]
    agent = await create_agent(client, max_tool_calls=1)
    conv = await create_conversation(client, agent["id"])

    events = await send_message(client, conv["id"], "Add things")
    assert events[-1]["data"]["code"] == "limit_exceeded"
    roles = [
        m["role"] for m in (await client.get(f"/api/conversations/{conv['id']}")).json()["messages"]
    ]
    assert roles == ["user", "assistant", "tool", "tool"]

    events = await send_message(client, conv["id"], "Continue")
    assert events[-1]["event"] == "run.completed"


async def _start_slow_run(
    client: AsyncClient, app: FastAPI, fake_provider: FakeProvider
) -> tuple[str, "asyncio.Task[Response]", uuid.UUID]:
    fake_provider.model.delay_s = 10
    fake_provider.model.responses = [reply("never delivered")]
    agent = await create_agent(client)
    conv = await create_conversation(client, agent["id"])
    task = asyncio.create_task(
        client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "slow"})
    )
    manager = app.state.run_manager
    for _ in range(200):
        if (run_id := manager.active_run_id(uuid.UUID(conv["id"]))) is not None:
            return conv["id"], task, run_id
        await asyncio.sleep(0.01)
    raise AssertionError("run did not start")


async def test_cancel_endpoint(
    client: AsyncClient, app: FastAPI, fake_provider: FakeProvider
) -> None:
    conv_id, task, run_id = await _start_slow_run(client, app, fake_provider)

    assert (await client.post(f"/api/runs/{run_id}/cancel")).status_code == 202
    events = parse_sse((await asyncio.wait_for(task, timeout=5)).text)
    assert types(events) == ["run.started", "run.cancelled"]

    run = (await client.get(f"/api/runs/{run_id}")).json()
    assert run["status"] == "cancelled"
    messages = (await client.get(f"/api/conversations/{conv_id}")).json()["messages"]
    assert [m["role"] for m in messages] == ["user"]

    assert (await client.post(f"/api/runs/{run_id}/cancel")).status_code == 409
    assert (await client.post(f"/api/runs/{uuid.uuid4()}/cancel")).status_code == 404


async def test_second_message_while_running_is_409(
    client: AsyncClient, app: FastAPI, fake_provider: FakeProvider
) -> None:
    conv_id, task, run_id = await _start_slow_run(client, app, fake_provider)
    resp = await client.post(f"/api/conversations/{conv_id}/messages", json={"content": "again"})
    assert resp.status_code == 409
    app.state.run_manager.cancel(run_id)
    await asyncio.wait_for(task, timeout=5)


async def test_history_survives_app_restart(
    client: AsyncClient, fake_provider: FakeProvider, app: FastAPI
) -> None:
    fake_provider.model.responses = [reply("Persisted answer.")]
    agent = await create_agent(client, tools=[])
    conv = await create_conversation(client, agent["id"])
    await send_message(client, conv["id"], "Remember this")

    # A brand-new app instance (fresh registries, fresh run manager) sees the same data.
    fresh = create_app(app.state.settings)
    fresh.dependency_overrides = dict(app.dependency_overrides)
    async with AsyncClient(transport=ASGITransport(app=fresh), base_url="http://test") as c2:
        detail = (await c2.get(f"/api/conversations/{conv['id']}")).json()
        assert [m["content"] for m in detail["messages"]] == ["Remember this", "Persisted answer."]
        run_id = detail["runs"][0]["id"]
        assert len((await c2.get(f"/api/runs/{run_id}/events")).json()) >= 3


async def test_runs_unknown_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await client.get(f"/api/runs/{missing}")).status_code == 404
    assert (await client.get(f"/api/runs/{missing}/events")).status_code == 404


async def test_mark_interrupted_runs(client: AsyncClient, session: AsyncSession) -> None:
    agent = await create_agent(client)
    conv = await create_conversation(client, agent["id"])
    run = Run(conversation_id=uuid.UUID(conv["id"]), agent_id=uuid.UUID(agent["id"]))
    session.add(run)
    await session.commit()

    assert await mark_interrupted_runs(session) == 1
    refreshed = (await client.get(f"/api/runs/{run.id}")).json()
    assert refreshed["status"] == "failed"
    assert refreshed["error"] == "Interrupted by a server restart"
