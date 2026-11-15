"""Workflows over HTTP: drafts, validation, versions, durable runs through the worker,
real agent/tool/knowledge nodes, approval continuation, RBAC and isolation."""

import asyncio
from typing import Any

from httpx import AsyncClient

from tests.conftest import UserClientFactory
from tests.fakes import FakeProvider, reply
from tests.sse_helpers import create_agent, parse_sse


def node(nid: str, ntype: str, **config: Any) -> dict[str, Any]:
    return {"id": nid, "type": ntype, "config": config}


def edges(*pairs: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {"source": p[0], "target": p[1], "source_handle": p[2] if len(p) > 2 else None}
        for p in pairs
    ]


def llm_chain() -> dict[str, Any]:
    return {
        "nodes": [
            node("start", "start", inputs=[{"name": "topic"}]),
            node("write", "llm", model="fake-tools:1b", prompt="Write about {{ input.topic }}"),
            node("calc", "tool", tool="calculator", args={"expression": "6*7"}),
            node("end", "end", output="{{ write }} | {{ calc }}"),
        ],
        "edges": edges(("start", "write"), ("write", "calc"), ("calc", "end")),
    }


async def _create(client: AsyncClient, spec: dict[str, Any], name: str = "Flow") -> dict[str, Any]:
    resp = await client.post("/api/workflows", json={"name": name, "spec": spec})
    assert resp.status_code == 201, resp.text
    wf: dict[str, Any] = resp.json()
    return wf


async def _run(
    client: AsyncClient, wf_id: str, inputs: dict[str, str], **extra: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    resp = await client.post(f"/api/workflows/{wf_id}/runs", json={"inputs": inputs} | extra)
    assert resp.status_code == 201, resp.text
    run: dict[str, Any] = resp.json()
    stream = await asyncio.wait_for(client.get(f"/api/runs/{run['id']}/stream"), timeout=20)
    return run, parse_sse(stream.text)


async def test_run_a_workflow_end_to_end(client: AsyncClient, fake_provider: FakeProvider) -> None:
    wf = await _create(client, llm_chain())
    assert wf["node_count"] == 4
    fake_provider.model.responses = [reply("A short essay.")]
    run, events = await _run(client, wf["id"], {"topic": "tides"})
    assert run["kind"] == "workflow" and run["inputs"] == {"topic": "tides"}
    types = [e["event"] for e in events if e["event"] != "message.delta"]
    assert types[0] == "run.started" and types[-1] == "run.completed"
    done = [e["data"]["node_id"] for e in events if e["event"] == "node.completed"]
    assert done == ["start", "write", "calc", "end"]
    assert events[-1]["data"]["output"] == "A short essay. | 42"
    stored = (await client.get(f"/api/runs/{run['id']}")).json()
    assert stored["status"] == "completed" and stored["output"] == "A short essay. | 42"
    assert fake_provider.model.prompts[-1][-1].content == "Write about tides"
    runs = (await client.get(f"/api/workflows/{wf['id']}/runs")).json()
    assert [r["id"] for r in runs] == [run["id"]]
    timeline = (await client.get(f"/api/runs/{run['id']}/events")).json()
    assert {"node.started", "node.completed", "run.completed"} <= {e["type"] for e in timeline}


async def test_validation_drafts_and_versions(client: AsyncClient) -> None:
    broken = {
        "nodes": [node("start", "start"), node("x", "llm", model="m", prompt="p")],
        "edges": [],
    }
    result = (await client.post("/api/workflows/validate", json=broken)).json()
    assert result["valid"] is False and result["problems"]
    wf = await _create(client, broken, name="Draft")  # incomplete drafts can be saved
    assert (await client.post(f"/api/workflows/{wf['id']}/publish", json={})).status_code == 422
    resp = await client.post(f"/api/workflows/{wf['id']}/runs", json={"inputs": {}})
    assert resp.status_code == 422

    good = llm_chain()
    updated = await client.put(f"/api/workflows/{wf['id']}", json={"name": "Draft", "spec": good})
    assert updated.status_code == 200
    assert (
        await client.post(f"/api/workflows/{wf['id']}/publish", json={"note": "v1"})
    ).status_code == 201
    unknown = {
        **good,
        "nodes": [*good["nodes"][:2], node("calc", "tool", tool="rm_rf"), good["nodes"][3]],
    }
    problems = (await client.post("/api/workflows/validate", json=unknown)).json()["problems"]
    assert any("Unknown tool" in p["message"] for p in problems)
    await client.put(f"/api/workflows/{wf['id']}", json={"name": "Draft", "spec": broken})
    versions = (await client.get(f"/api/workflows/{wf['id']}/versions")).json()
    assert [v["version"] for v in versions] == [1]
    restored = (await client.post(f"/api/workflows/{wf['id']}/versions/1/restore")).json()
    assert restored["node_count"] == 4
    # Missing inputs are rejected before queueing.
    resp = await client.post(f"/api/workflows/{wf['id']}/runs", json={"inputs": {}})
    assert resp.status_code == 422 and "topic" in resp.json()["detail"]
    # Reserved/duplicate ids are rejected even for drafts.
    dup = {"nodes": [node("a", "start"), node("a", "end")], "edges": []}
    assert (await client.post("/api/workflows", json={"name": "x", "spec": dup})).status_code == 422


async def test_agent_node_and_spec_references(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    agent = await create_agent(client, tools=[], system_prompt="You are terse.")
    spec = {
        "nodes": [
            node("start", "start", inputs=[{"name": "q"}]),
            node(
                "ask", "agent", agent_id=agent["id"], prompt="Answer: {{ input.q }}", use_draft=True
            ),
            node("end", "end", output="{{ ask }}"),
        ],
        "edges": edges(("start", "ask"), ("ask", "end")),
    }
    wf = await _create(client, spec)
    fake_provider.model.responses = [reply("Forty-two.")]
    _, events = await _run(client, wf["id"], {"q": "meaning of life?"})
    assert events[-1]["data"]["output"] == "Forty-two."
    assert "You are terse." in str(fake_provider.model.prompts[-1][0].content)

    bad = {
        **spec,
        "nodes": [
            spec["nodes"][0],
            node("ask", "agent", agent_id="00000000-0000-0000-0000-000000000000", prompt="x"),
            spec["nodes"][2],
        ],
    }
    problems = (await client.post("/api/workflows/validate", json=bad)).json()["problems"]
    assert any(p["message"] == "Unknown agent" for p in problems)


async def test_approval_node_resumes_after_decision(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    spec = {
        "nodes": [
            node("start", "start"),
            node("draft", "llm", model="fake-tools:1b", prompt="Draft a post"),
            node("review", "approval", message="Publish? {{ draft }}"),
            node("pub", "end", output="published: {{ draft }}"),
            node("rej", "end", output="held back"),
        ],
        "edges": edges(
            ("start", "draft"),
            ("draft", "review"),
            ("review", "pub", "approved"),
            ("review", "rej", "rejected"),
        ),
    }
    wf = await _create(client, spec)
    fake_provider.model.responses = [reply("Hello world")]
    run, events = await _run(client, wf["id"], {})
    assert events[-1]["event"] == "run.waiting_approval"
    (approval,) = (await client.get("/api/approvals")).json()
    assert (
        approval["tool_name"] == "workflow.approval"
        and approval["args"]["message"] == "Publish? Hello world"
    )
    result = (
        await client.post(f"/api/approvals/{approval['id']}/decide", json={"decision": "approve"})
    ).json()
    cont = result["continuation_run_id"]
    stream = parse_sse(
        (await asyncio.wait_for(client.get(f"/api/runs/{cont}/stream"), timeout=20)).text
    )
    assert (
        stream[-1]["event"] == "run.completed"
        and stream[-1]["data"]["output"] == "published: Hello world"
    )
    assert len(fake_provider.model.prompts) == 1  # the draft step did not run again


async def test_rbac_and_isolation(client: AsyncClient, make_client: UserClientFactory) -> None:
    wf = await _create(client, llm_chain())
    other = await make_client("other@example.com")
    assert (await other.get("/api/workflows")).json() == []
    for method, path in (
        ("GET", f"/api/workflows/{wf['id']}"),
        ("POST", f"/api/workflows/{wf['id']}/runs"),
        ("DELETE", f"/api/workflows/{wf['id']}"),
    ):
        resp = await other.request(
            method, path, json={"inputs": {"topic": "x"}} if method == "POST" else None
        )
        assert resp.status_code == 404, path
    viewer = await make_client("viewer@example.com")
    await client.post("/api/members", json={"email": "viewer@example.com", "role": "viewer"})
    viewer.headers["X-Workspace-Id"] = (await client.get("/api/auth/me")).json()[
        "current_workspace_id"
    ]
    assert (await viewer.get(f"/api/workflows/{wf['id']}")).status_code == 200
    assert (
        await viewer.post(f"/api/workflows/{wf['id']}/runs", json={"inputs": {"topic": "x"}})
    ).status_code == 403
    assert (
        await viewer.put(f"/api/workflows/{wf['id']}", json={"name": "x", "spec": llm_chain()})
    ).status_code == 403


async def test_node_types_and_templates_are_valid(client: AsyncClient) -> None:
    types = (await client.get("/api/workflow-node-types")).json()
    assert {
        "start",
        "end",
        "agent",
        "llm",
        "tool",
        "knowledge",
        "memory",
        "condition",
        "router",
        "parallel",
        "approval",
        "supervisor",
    } == set(types)
    for template in (await client.get("/api/workflow-templates")).json():
        result = (await client.post("/api/workflows/validate", json=template["spec"])).json()
        # Templates reference the default model; with the fake provider only structure matters.
        assert (
            all("Unknown model provider" in p["message"] or not p for p in result["problems"])
            or result["valid"]
        ), template["id"]


async def test_supervisor_team_end_to_end(client: AsyncClient, fake_provider: FakeProvider) -> None:
    from tests.fakes import tool_call

    researcher = await create_agent(
        client, name="Researcher", tools=[], system_prompt="Find facts."
    )
    spec = {
        "nodes": [
            node("start", "start", inputs=[{"name": "topic"}]),
            node(
                "team",
                "supervisor",
                model="fake-tools:1b",
                task="Explain {{ input.topic }}",
                members=[{"name": "researcher", "agent_id": researcher["id"], "role": "facts"}],
                max_delegations=2,
            ),
            node("end", "end", output="{{ team }}"),
        ],
        "edges": edges(("start", "team"), ("team", "end")),
    }
    wf = await _create(client, spec, name="Team")
    fake_provider.model.responses = [
        reply(
            "",
            tool_call(
                "delegate",
                {"member": "researcher", "task": "Facts about tides", "reason": "needs facts"},
                "d1",
            ),
        ),
        reply("Tides are caused by the moon."),  # the member agent
        reply("", tool_call("finish", {"answer": "Tides: the moon pulls the oceans."}, "f1")),
    ]
    _, events = await _run(client, wf["id"], {"topic": "tides"})
    delegated = next(e for e in events if e["event"] == "agent.delegated")["data"]
    assert (delegated["member"], delegated["reason"], delegated["agent_id"]) == (
        "researcher",
        "needs facts",
        researcher["id"],
    )
    result = next(e for e in events if e["event"] == "agent.result")["data"]
    assert result["output"] == "Tides are caused by the moon." and result["ok"] is True
    assert events[-1]["data"]["output"] == "Tides: the moon pulls the oceans."
    # The member ran with its own instructions and only the delegated task.
    member_prompt = fake_provider.model.prompts[1]
    assert (
        "Find facts." in str(member_prompt[0].content)
        and member_prompt[-1].content == "Facts about tides"
    )

    bad = {
        **spec,
        "nodes": [
            spec["nodes"][0],
            node(
                "team",
                "supervisor",
                model="m",
                task="t",
                members=[{"name": "x", "agent_id": "00000000-0000-0000-0000-000000000000"}],
            ),
            spec["nodes"][2],
        ],
    }
    problems = (await client.post("/api/workflows/validate", json=bad)).json()["problems"]
    assert any("Unknown agent for member" in p["message"] for p in problems)
