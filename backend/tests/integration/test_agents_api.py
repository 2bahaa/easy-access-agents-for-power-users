import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AgentSkill, AgentTool, Conversation


def agent_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "Math helper",
        "description": "Answers arithmetic",
        "model": "llama3.2:1b",
        "model_params": {"temperature": 0.2},
        "system_prompt": "You are precise.",
        "tools": [{"name": "calculator", "config": {}}],
    } | overrides


async def make_skill(client: AsyncClient, slug: str) -> str:
    resp = await client.post("/api/skills", json={"slug": slug, "name": slug.title()})
    assert resp.status_code == 201, resp.text
    skill_id: str = resp.json()["id"]
    return skill_id


async def test_agent_crud_roundtrip(client: AsyncClient) -> None:
    s1 = await make_skill(client, "first")
    created = await client.post("/api/agents", json=agent_payload(skill_ids=[s1]))
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["provider"] == "ollama"
    assert agent["model_params"] == {"temperature": 0.2, "num_ctx": None, "think": None}
    assert [s["slug"] for s in agent["skills"]] == ["first"]
    assert agent["tools"] == [{"name": "calculator", "config": {}}]
    assert agent["max_tool_calls"] == 8 and agent["run_timeout_s"] == 120

    listed = (await client.get("/api/agents")).json()
    assert [a["id"] for a in listed] == [agent["id"]]
    assert "system_prompt" not in listed[0]

    fetched = (await client.get(f"/api/agents/{agent['id']}")).json()
    assert fetched == agent

    assert (await client.delete(f"/api/agents/{agent['id']}")).status_code == 204
    assert (await client.get(f"/api/agents/{agent['id']}")).status_code == 404


async def test_put_replaces_skills_and_tools_in_order(
    client: AsyncClient, session: AsyncSession
) -> None:
    a, b, c = [await make_skill(client, s) for s in ("alpha", "beta", "gamma")]
    agent = (await client.post("/api/agents", json=agent_payload(skill_ids=[a, b]))).json()

    resp = await client.put(
        f"/api/agents/{agent['id']}",
        json=agent_payload(
            name="Renamed",
            skill_ids=[c, a],
            tools=[{"name": "file_reader", "config": {"subdir": "notes"}}],
        ),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Renamed"
    assert [s["slug"] for s in body["skills"]] == ["gamma", "alpha"]
    assert body["tools"] == [{"name": "file_reader", "config": {"subdir": "notes"}}]
    assert body["updated_at"] >= agent["updated_at"]

    links = await session.scalar(select(func.count()).select_from(AgentSkill))
    tools = await session.scalar(select(func.count()).select_from(AgentTool))
    assert (links, tools) == (2, 1)


async def test_unknown_skill_id_is_422(client: AsyncClient) -> None:
    resp = await client.post("/api/agents", json=agent_payload(skill_ids=[str(uuid.uuid4())]))
    assert resp.status_code == 422
    assert "Unknown skill" in resp.json()["detail"]


async def test_limits_above_global_caps_are_422(client: AsyncClient, settings: Settings) -> None:
    too_many = agent_payload(max_tool_calls=settings.max_tool_calls_cap + 1)
    assert (await client.post("/api/agents", json=too_many)).status_code == 422
    too_long = agent_payload(run_timeout_s=settings.run_timeout_cap_s + 1)
    assert (await client.post("/api/agents", json=too_long)).status_code == 422


async def test_schema_validation_errors(client: AsyncClient) -> None:
    cases: list[dict[str, Any]] = [
        agent_payload(name=""),
        agent_payload(model_params={"temperature": 5}),
        agent_payload(model_params={"unknown": 1}),
        agent_payload(tools=[{"name": "calculator"}, {"name": "calculator"}]),
        agent_payload(max_tool_calls=0),
        agent_payload(extra_field=True),
    ]
    for payload in cases:
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 422, payload


async def test_unknown_agent_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await client.get(f"/api/agents/{missing}")).status_code == 404
    assert (await client.put(f"/api/agents/{missing}", json=agent_payload())).status_code == 404
    assert (await client.delete(f"/api/agents/{missing}")).status_code == 404


async def test_deleting_skill_detaches_it(client: AsyncClient) -> None:
    s = await make_skill(client, "temp")
    agent = (await client.post("/api/agents", json=agent_payload(skill_ids=[s]))).json()
    assert (await client.delete(f"/api/skills/{s}")).status_code == 204
    assert (await client.get(f"/api/agents/{agent['id']}")).json()["skills"] == []


async def test_deleting_agent_cascades(client: AsyncClient, session: AsyncSession) -> None:
    agent = (await client.post("/api/agents", json=agent_payload())).json()
    ws = (await client.get("/api/auth/me")).json()["current_workspace_id"]
    session.add(Conversation(workspace_id=uuid.UUID(ws), agent_id=uuid.UUID(agent["id"])))
    await session.commit()
    assert (await client.delete(f"/api/agents/{agent['id']}")).status_code == 204
    assert await session.scalar(select(func.count()).select_from(Conversation)) == 0
    assert await session.scalar(select(func.count()).select_from(AgentTool)) == 0
