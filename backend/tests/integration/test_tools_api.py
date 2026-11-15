from typing import Any

from httpx import AsyncClient


def agent_payload(tools: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": "Tool agent", "model": "llama3.2:1b", "tools": tools}


async def test_list_tools(client: AsyncClient) -> None:
    resp = await client.get("/api/tools")
    assert resp.status_code == 200
    tools = {t["name"]: t for t in resp.json()}
    assert set(tools) == {"calculator", "file_reader"}
    calc = tools["calculator"]
    assert calc["args_schema"]["required"] == ["expression"]
    assert calc["timeout_s"] == 2.0
    assert "subdir" in tools["file_reader"]["config_schema"]["properties"]


async def test_unknown_tool_is_422(client: AsyncClient) -> None:
    resp = await client.post("/api/agents", json=agent_payload([{"name": "shell"}]))
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Unknown tool: 'shell'"


async def test_invalid_tool_config_is_422(client: AsyncClient) -> None:
    bad = [{"name": "file_reader", "config": {"subdir": "../outside"}}]
    resp = await client.post("/api/agents", json=agent_payload(bad))
    assert resp.status_code == 422
    assert "file_reader" in resp.json()["detail"]

    extra = [{"name": "calculator", "config": {"mode": "unsafe"}}]
    assert (await client.post("/api/agents", json=agent_payload(extra))).status_code == 422


async def test_tool_config_is_normalized_on_save(client: AsyncClient) -> None:
    tools = [{"name": "file_reader", "config": {"subdir": "notes\\"}}, {"name": "calculator"}]
    resp = await client.post("/api/agents", json=agent_payload(tools))
    assert resp.status_code == 201, resp.text
    assert resp.json()["tools"] == [
        {"name": "calculator", "config": {}, "requires_approval": False},
        {"name": "file_reader", "config": {"subdir": "notes"}, "requires_approval": False},
    ]


async def test_update_with_unknown_tool_leaves_agent_unchanged(client: AsyncClient) -> None:
    agent = (await client.post("/api/agents", json=agent_payload([{"name": "calculator"}]))).json()
    resp = await client.put(f"/api/agents/{agent['id']}", json=agent_payload([{"name": "shell"}]))
    assert resp.status_code == 422
    current = (await client.get(f"/api/agents/{agent['id']}")).json()
    assert current["tools"] == [{"name": "calculator", "config": {}, "requires_approval": False}]
