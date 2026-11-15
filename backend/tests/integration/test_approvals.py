"""Human-in-the-loop: held tool calls, decisions, continuation runs, policies, expiry."""

import asyncio
import uuid
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update

from app.db.models import ApprovalRequest
from app.services import approval_service
from tests.conftest import UserClientFactory
from tests.fakes import FakeProvider, reply, tool_call
from tests.integration.test_runs_api import wait_for_status
from tests.sse_helpers import create_agent, create_conversation, parse_sse, send_message

CALC = {"name": "calculator", "requires_approval": True}


def types(events: list[dict[str, Any]]) -> list[str]:
    return [e["event"] for e in events]


async def _paused(
    client: AsyncClient,
    fake: FakeProvider,
    *,
    tools: list[dict[str, Any]] | None = None,
    calls: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    agent = await create_agent(client, tools=tools or [CALC])
    conv = await create_conversation(client, agent["id"])
    fake.model.responses = [
        reply("", *(calls or [tool_call("calculator", {"expression": "6*7"}, "c1")]))
    ]
    events = await send_message(client, conv["id"], "compute")
    return agent, conv, events


async def _approvals(client: AsyncClient, **params: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = (await client.get("/api/approvals", params=params)).json()
    return items


async def _follow(client: AsyncClient, run_id: str) -> list[dict[str, Any]]:
    resp = await asyncio.wait_for(client.get(f"/api/runs/{run_id}/stream"), timeout=15)
    return parse_sse(resp.text)


async def test_tool_call_is_held_and_approved(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    agent, conv, events = await _paused(client, fake_provider)
    assert types(events) == ["run.started", "approval.requested", "run.waiting_approval"]
    run_id = events[0]["data"]["run_id"]
    assert events[1]["data"] == {
        **events[1]["data"],
        "call_id": "c1",
        "tool": "calculator",
        "args": {"expression": "6*7"},
    }
    assert (await client.get(f"/api/runs/{run_id}")).json()["status"] == "waiting_approval"

    detail = (await client.get(f"/api/conversations/{conv['id']}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]  # not executed yet
    # The conversation is busy until the approval is resolved.
    resp = await client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "again"})
    assert resp.status_code == 409

    (pending,) = await _approvals(client)
    assert (pending["tool_name"], pending["args"], pending["status"]) == (
        "calculator",
        {"expression": "6*7"},
        "pending",
    )

    fake_provider.model.responses = [reply("It is 42.")]
    result = (
        await client.post(f"/api/approvals/{pending['id']}/decide", json={"decision": "approve"})
    ).json()
    assert result["approval"]["status"] == "approved" and result["approval"]["decided_by"]
    cont_id = result["continuation_run_id"]
    assert cont_id

    cont_events = [e for e in await _follow(client, cont_id) if e["event"] != "message.delta"]
    assert types(cont_events) == [
        "run.started",
        "tool.call.started",
        "tool.call.completed",
        "message.completed",
        "run.completed",
    ]
    assert cont_events[2]["data"]["result"] == "42"
    cont = (await client.get(f"/api/runs/{cont_id}")).json()
    assert cont["resume_of"] == run_id and cont["status"] == "completed"
    assert (await client.get(f"/api/runs/{run_id}")).json()["status"] == "resumed"
    roles = [
        m["role"] for m in (await client.get(f"/api/conversations/{conv['id']}")).json()["messages"]
    ]
    assert roles == ["user", "assistant", "tool", "assistant"]
    # The model saw the approved result before answering.
    last_prompt = fake_provider.model.prompts[-1]
    assert type(last_prompt[-1]).__name__ == "ToolMessage" and last_prompt[-1].content == "42"


async def test_rejection_and_edited_arguments(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    _, conv, _ = await _paused(client, fake_provider)
    (pending,) = await _approvals(client)
    fake_provider.model.responses = [reply("Understood, I will not compute that.")]
    result = (
        await client.post(
            f"/api/approvals/{pending['id']}/decide", json={"decision": "reject", "note": "not now"}
        )
    ).json()
    events = await _follow(client, result["continuation_run_id"])
    failed = next(e for e in events if e["event"] == "tool.call.failed")
    assert failed["data"]["kind"] == "permission" and "not now" in failed["data"]["error"]
    assert events[-1]["event"] == "run.completed"

    # Approve with corrected arguments (validated like any model call).
    fake_provider.model.responses = [
        reply("", tool_call("calculator", {"expression": "1/0"}, "c2"))
    ]
    await send_message(client, conv["id"], "risky")
    (pending,) = await _approvals(client)
    fake_provider.model.responses = [reply("2")]
    result = (
        await client.post(
            f"/api/approvals/{pending['id']}/decide",
            json={"decision": "approve", "args": {"expression": "1+1"}},
        )
    ).json()
    assert result["approval"]["edited_args"] == {"expression": "1+1"}
    completed = next(
        e
        for e in await _follow(client, result["continuation_run_id"])
        if e["event"] == "tool.call.completed"
    )
    assert completed["data"]["result"] == "2"

    fake_provider.model.responses = [
        reply("", tool_call("calculator", {"expression": "3*3"}, "c3"))
    ]
    await send_message(client, conv["id"], "again")
    (pending,) = await _approvals(client)
    fake_provider.model.responses = [reply("ok")]
    result = (
        await client.post(
            f"/api/approvals/{pending['id']}/decide",
            json={"decision": "approve", "args": {"wrong": 1}},
        )
    ).json()
    failed = next(
        e
        for e in await _follow(client, result["continuation_run_id"])
        if e["event"] == "tool.call.failed"
    )
    assert failed["data"]["kind"] == "validation"


async def test_only_flagged_calls_wait(
    client: AsyncClient, fake_provider: FakeProvider, settings: Any
) -> None:
    (settings.workspace_dir).mkdir(parents=True, exist_ok=True)
    _, _, events = await _paused(
        client,
        fake_provider,
        tools=[CALC, {"name": "file_reader"}],
        calls=[
            tool_call("calculator", {"expression": "1+1"}, "a"),
            tool_call("file_reader", {"path": "x.txt"}, "b"),
        ],
    )
    # file_reader ran immediately (and failed: no such file); only the calculator waits.
    assert types(events) == [
        "run.started",
        "approval.requested",
        "tool.call.started",
        "tool.call.failed",
        "run.waiting_approval",
    ]
    assert events[-1]["data"]["pending"] == ["a"]


async def test_workspace_policy_requires_approval(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    resp = await client.post("/api/approval-policies", json={"tool_pattern": "calc*"})
    assert resp.status_code == 201
    _, _, events = await _paused(client, fake_provider, tools=[{"name": "calculator"}])
    assert events[-1]["event"] == "run.waiting_approval"
    policies = (await client.get("/api/approval-policies")).json()
    assert [p["tool_pattern"] for p in policies] == ["calc*"]
    assert (await client.delete(f"/api/approval-policies/{policies[0]['id']}")).status_code == 204
    assert (
        await client.post("/api/approval-policies", json={"tool_pattern": "bad pattern!"})
    ).status_code == 422


async def test_who_may_decide(
    client: AsyncClient, fake_provider: FakeProvider, make_client: UserClientFactory
) -> None:
    await _paused(client, fake_provider)
    (pending,) = await _approvals(client)
    other = await make_client("other@example.com")
    assert await _approvals(other) == []
    resp = await other.post(f"/api/approvals/{pending['id']}/decide", json={"decision": "approve"})
    assert resp.status_code == 404
    viewer = await make_client("viewer@example.com")
    await client.post("/api/members", json={"email": "viewer@example.com", "role": "viewer"})
    viewer.headers["X-Workspace-Id"] = (await client.get("/api/auth/me")).json()[
        "current_workspace_id"
    ]
    resp = await viewer.post(f"/api/approvals/{pending['id']}/decide", json={"decision": "approve"})
    assert resp.status_code == 403
    assert (
        await viewer.post("/api/approval-policies", json={"tool_pattern": "x"})
    ).status_code == 403

    fake_provider.model.responses = [reply("done")]
    assert (
        await client.post(f"/api/approvals/{pending['id']}/decide", json={"decision": "reject"})
    ).status_code == 200
    again = await client.post(
        f"/api/approvals/{pending['id']}/decide", json={"decision": "approve"}
    )
    assert again.status_code == 409
    audit = [e["action"] for e in (await client.get("/api/audit")).json()]
    assert "approval.rejected" in audit


async def test_expired_requests_resume_as_rejected(
    client: AsyncClient, fake_provider: FakeProvider, app: FastAPI
) -> None:
    await _paused(client, fake_provider)
    (pending,) = await _approvals(client)
    async with app.state.sessionmaker() as session:
        await session.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == uuid.UUID(pending["id"]))
            .values(expires_at=ApprovalRequest.created_at)
        )
        await session.commit()
    fake_provider.model.responses = [reply("Okay.")]
    async with app.state.sessionmaker() as session:
        assert await approval_service.expire_due(session) == 1
    (expired,) = await _approvals(client, status="expired")
    assert expired["id"] == pending["id"]
    cont = await wait_for_status(
        client,
        _continuation_of(await _runs(client, expired["conversation_id"]), expired["run_id"]),
        "completed",
    )
    assert cont["resume_of"] == expired["run_id"]


async def _runs(client: AsyncClient, conversation_id: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = (await client.get(f"/api/conversations/{conversation_id}")).json()[
        "runs"
    ]
    return runs


def _continuation_of(runs: list[dict[str, Any]], run_id: str) -> str:
    return next(r["id"] for r in runs if r.get("resume_of") == run_id)


async def test_cancelling_a_waiting_run(client: AsyncClient, fake_provider: FakeProvider) -> None:
    _, conv, events = await _paused(client, fake_provider)
    run_id = events[0]["data"]["run_id"]
    assert (await client.post(f"/api/runs/{run_id}/cancel")).status_code == 202
    assert (await client.get(f"/api/runs/{run_id}")).json()["status"] == "cancelled"
    (cancelled,) = await _approvals(client, status="cancelled")
    resp = await client.post(
        f"/api/approvals/{cancelled['id']}/decide", json={"decision": "approve"}
    )
    assert resp.status_code == 409
    # The conversation is free again.
    fake_provider.model.responses = [reply("hello")]
    events = await send_message(client, conv["id"], "hi")
    assert events[-1]["event"] == "run.completed"
