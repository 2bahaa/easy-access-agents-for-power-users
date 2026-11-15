"""End-to-end over HTTP: POST message -> SSE stream -> persisted messages, runs, events."""

import asyncio
import uuid
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from langchain_core.messages import ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, Conversation, Run, Workspace
from app.main import create_app
from app.services.run_service import list_run_events, mark_interrupted_runs
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


async def wait_for_status(
    client: AsyncClient, run_id: uuid.UUID | str, *statuses: str, within_s: float = 5
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + within_s
    while True:
        run: dict[str, Any] = (await client.get(f"/api/runs/{run_id}")).json()
        if run["status"] in statuses:
            return run
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"run stayed {run['status']}, expected {statuses}")
        await asyncio.sleep(0.02)


async def active_run(client: AsyncClient, conv_id: str, within_s: float = 5) -> uuid.UUID:
    """Wait until the conversation has a running run and return its id."""
    deadline = asyncio.get_running_loop().time() + within_s
    while asyncio.get_running_loop().time() < deadline:
        runs = (await client.get(f"/api/conversations/{conv_id}")).json()["runs"]
        if runs and runs[-1]["status"] == "running":
            return uuid.UUID(runs[-1]["id"])
        await asyncio.sleep(0.02)
    raise AssertionError("run did not start")


async def _start_slow_run(
    client: AsyncClient, fake_provider: FakeProvider
) -> tuple[str, "asyncio.Task[Response]", uuid.UUID]:
    fake_provider.model.delay_s = 10
    fake_provider.model.responses = [reply("never delivered")]
    agent = await create_agent(client)
    conv = await create_conversation(client, agent["id"])
    task = asyncio.create_task(
        client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "slow"})
    )
    return conv["id"], task, await active_run(client, conv["id"])


async def test_cancel_endpoint(client: AsyncClient, fake_provider: FakeProvider) -> None:
    conv_id, task, run_id = await _start_slow_run(client, fake_provider)

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
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    conv_id, task, run_id = await _start_slow_run(client, fake_provider)
    resp = await client.post(f"/api/conversations/{conv_id}/messages", json={"content": "again"})
    assert resp.status_code == 409
    await client.post(f"/api/runs/{run_id}/cancel")
    await asyncio.wait_for(task, timeout=5)


async def test_history_survives_app_restart(
    client: AsyncClient, fake_provider: FakeProvider, app: FastAPI
) -> None:
    fake_provider.model.responses = [reply("Persisted answer.")]
    agent = await create_agent(client, tools=[])
    conv = await create_conversation(client, agent["id"])
    await send_message(client, conv["id"], "Remember this")

    # A brand-new app instance (fresh engine, registries and worker) sees the same data.
    fresh = create_app(app.state.settings, provider_registry=app.state.provider_registry)
    async with fresh.router.lifespan_context(fresh):
        async with AsyncClient(
            transport=ASGITransport(app=fresh),
            base_url="http://test",
            headers={"Authorization": client.headers["Authorization"]},  # same JWT secret
        ) as c2:
            detail = (await c2.get(f"/api/conversations/{conv['id']}")).json()
            assert [m["content"] for m in detail["messages"]] == [
                "Remember this",
                "Persisted answer.",
            ]
            run_id = detail["runs"][0]["id"]
            assert len((await c2.get(f"/api/runs/{run_id}/events")).json()) >= 3


async def test_runs_unknown_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await client.get(f"/api/runs/{missing}")).status_code == 404
    assert (await client.get(f"/api/runs/{missing}/events")).status_code == 404


async def test_mark_interrupted_runs(session: AsyncSession, workspace: Workspace) -> None:
    """Startup reaping (no worker running): active runs become failed with a terminal event."""
    ws = workspace.id
    agent = Agent(workspace_id=ws, name="A", provider="fake", model="tools:1b")
    session.add(agent)
    await session.flush()
    conv = Conversation(workspace_id=ws, agent_id=agent.id)
    session.add(conv)
    await session.flush()
    run = Run(workspace_id=ws, conversation_id=conv.id, agent_id=agent.id, status="running")
    session.add(run)
    await session.commit()

    assert await mark_interrupted_runs(session) == 1
    await session.refresh(run)
    assert run.status == "failed"
    assert run.error == "Interrupted by a server restart"
    (event,) = await list_run_events(session, run.id, ws)
    assert event.type == "run.failed" and event.payload["code"] == "internal_error"
