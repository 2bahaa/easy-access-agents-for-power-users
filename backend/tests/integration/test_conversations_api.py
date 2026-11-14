import uuid

from httpx import AsyncClient

from tests.sse_helpers import create_agent, create_conversation


async def test_conversation_crud(client: AsyncClient) -> None:
    agent = await create_agent(client)
    other = await create_agent(client, name="Other")
    conv = await create_conversation(client, agent["id"])
    assert conv["title"] == "New conversation"
    await create_conversation(client, other["id"])

    listed = (await client.get("/api/conversations", params={"agent_id": agent["id"]})).json()
    assert [c["id"] for c in listed] == [conv["id"]]
    assert len((await client.get("/api/conversations")).json()) == 2

    detail = (await client.get(f"/api/conversations/{conv['id']}")).json()
    assert detail["messages"] == [] and detail["runs"] == []

    assert (await client.delete(f"/api/conversations/{conv['id']}")).status_code == 204
    assert (await client.get(f"/api/conversations/{conv['id']}")).status_code == 404


async def test_custom_title(client: AsyncClient) -> None:
    agent = await create_agent(client)
    resp = await client.post(
        "/api/conversations", json={"agent_id": agent["id"], "title": "Budget questions"}
    )
    assert resp.json()["title"] == "Budget questions"


async def test_unknown_agent_is_422(client: AsyncClient) -> None:
    resp = await client.post("/api/conversations", json={"agent_id": str(uuid.uuid4())})
    assert resp.status_code == 422


async def test_unknown_conversation_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await client.get(f"/api/conversations/{missing}")).status_code == 404
    assert (await client.delete(f"/api/conversations/{missing}")).status_code == 404
    resp = await client.post(f"/api/conversations/{missing}/messages", json={"content": "hi"})
    assert resp.status_code == 404


async def test_empty_message_is_422(client: AsyncClient) -> None:
    agent = await create_agent(client)
    conv = await create_conversation(client, agent["id"])
    resp = await client.post(f"/api/conversations/{conv['id']}/messages", json={"content": ""})
    assert resp.status_code == 422
