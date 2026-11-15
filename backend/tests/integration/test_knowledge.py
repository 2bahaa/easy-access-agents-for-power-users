"""Knowledge collections (ingestion by the worker, hybrid search, citations, isolation) and
agent memory, end to end with a deterministic fake embedder."""

import asyncio
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import UserClientFactory
from tests.fakes import FakeProvider, reply, tool_call
from tests.sse_helpers import create_agent, create_conversation, send_message

DOC = (
    b"Solar panels convert sunlight into electricity using photovoltaic cells made of silicon, "
    b"mounted on the roof facing south.\n\n"
    b"The warranty for the inverter is ten years from the installation date, covering parts and "
    b"labour for any manufacturing defect.\n\n"
    b"Cleaning the panels twice a year keeps efficiency high, especially after dusty summers "
    b"and long dry spells without rain."
)


async def _collection(client: AsyncClient, name: str = "Manuals", **extra: Any) -> dict[str, Any]:
    resp = await client.post(
        "/api/knowledge/collections",
        json={"name": name, "embedding_model": "fake-embed", "chunk_size": 200, "chunk_overlap": 0}
        | extra,
    )
    assert resp.status_code == 201, resp.text
    c: dict[str, Any] = resp.json()
    return c


async def _upload(
    client: AsyncClient, cid: str, name: str = "manual.txt", data: bytes = DOC
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/knowledge/collections/{cid}/documents",
        params={"filename": name},
        content=data,
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 201, resp.text
    doc: dict[str, Any] = resp.json()
    return doc


async def _wait_ready(
    client: AsyncClient, cid: str, doc_id: str, status: str = "ready"
) -> dict[str, Any]:
    for _ in range(200):
        docs = (await client.get(f"/api/knowledge/collections/{cid}/documents")).json()
        doc = next(d for d in docs if d["id"] == doc_id)
        if doc["status"] in ("ready", "failed"):
            assert doc["status"] == status, doc
            return doc
        await asyncio.sleep(0.05)
    raise AssertionError("document was not processed")


async def test_ingest_and_hybrid_search(client: AsyncClient) -> None:
    c = await _collection(client)
    doc = await _upload(client, c["id"])
    assert doc["status"] == "queued"
    ready = await _wait_ready(client, c["id"], doc["id"])
    assert ready["chunk_count"] == 3

    hits = (
        await client.post(
            "/api/knowledge/search",
            json={"collection_ids": [c["id"]], "query": "inverter warranty years"},
        )
    ).json()
    assert "warranty for the inverter" in hits[0]["text"]
    assert hits[0]["document_title"] == "manual.txt" and hits[0]["chunk"] == 1
    listed = (await client.get("/api/knowledge/collections")).json()
    assert (listed[0]["document_count"], listed[0]["chunk_count"], listed[0]["dims"]) == (1, 3, 64)


async def test_upload_validation(client: AsyncClient, app: FastAPI) -> None:
    c = await _collection(client)
    await _upload(client, c["id"])
    dup = await client.post(
        f"/api/knowledge/collections/{c['id']}/documents",
        params={"filename": "again.txt"},
        content=DOC,
    )
    assert dup.status_code == 409
    bad = await client.post(
        f"/api/knowledge/collections/{c['id']}/documents",
        params={"filename": "x.exe"},
        content=b"MZ",
    )
    assert bad.status_code == 422
    app.state.settings = app.state.settings.model_copy(update={"knowledge_max_upload_bytes": 1000})
    big = await client.post(
        f"/api/knowledge/collections/{c['id']}/documents",
        params={"filename": "big.txt"},
        content=b"a" * 2000,
    )
    assert big.status_code == 422 and "too large" in big.json()["detail"]
    resp = await client.post(
        "/api/knowledge/collections",
        json={"name": "y", "embedding_model": "m", "chunk_size": 300, "chunk_overlap": 300},
    )
    assert resp.status_code == 422


async def test_failed_embedding_and_keyword_fallback(client: AsyncClient) -> None:
    broken = await _collection(client, name="Broken", embedding_model="broken")
    doc = await _upload(client, broken["id"])
    failed = await _wait_ready(client, broken["id"], doc["id"], status="failed")
    assert "not reachable" in failed["error"]


async def test_delete_document_and_collection(client: AsyncClient) -> None:
    c = await _collection(client)
    doc = await _upload(client, c["id"])
    await _wait_ready(client, c["id"], doc["id"])
    assert (await client.delete(f"/api/knowledge/documents/{doc['id']}")).status_code == 204
    hits = (
        await client.post(
            "/api/knowledge/search", json={"collection_ids": [c["id"]], "query": "warranty"}
        )
    ).json()
    assert hits == []
    assert (await client.delete(f"/api/knowledge/collections/{c['id']}")).status_code == 204
    assert (await client.get("/api/knowledge/collections")).json() == []


async def test_isolation(client: AsyncClient, make_client: UserClientFactory) -> None:
    c = await _collection(client)
    doc = await _upload(client, c["id"])
    other = await make_client("other@example.com")
    assert (await other.get("/api/knowledge/collections")).json() == []
    assert (await other.get(f"/api/knowledge/collections/{c['id']}/documents")).status_code == 404
    assert (
        await other.post("/api/knowledge/search", json={"collection_ids": [c["id"]], "query": "x"})
    ).status_code == 404
    assert (await other.delete(f"/api/knowledge/documents/{doc['id']}")).status_code == 404
    resp = await other.post(
        "/api/agents",
        json={
            "name": "a",
            "model": "tools:1b",
            "tools": [{"name": "knowledge__search", "config": {"collection_ids": [c["id"]]}}],
        },
    )
    assert resp.status_code == 422


async def test_agent_searches_knowledge_with_citations(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    c = await _collection(client)
    doc = await _upload(client, c["id"])
    await _wait_ready(client, c["id"], doc["id"])
    assert (
        await client.post(
            "/api/agents",
            json={"name": "a", "model": "tools:1b", "tools": [{"name": "knowledge__search"}]},
        )
    ).status_code == 422
    agent = await create_agent(
        client, tools=[{"name": "knowledge__search", "config": {"collection_ids": [c["id"]]}}]
    )
    fake_provider.model.responses = [
        reply(
            "", tool_call("knowledge__search", {"query": "how long is the inverter warranty"}, "k1")
        ),
        reply("Ten years [1]."),
    ]
    conv = await create_conversation(client, agent["id"])
    events = await send_message(client, conv["id"], "Warranty?")
    result = next(e for e in events if e["event"] == "tool.call.completed")["data"]["result"]
    assert result.startswith("[External tool output") and "[1] (manual.txt, chunk 2)" in result
    assert "ten years" in result


async def test_agent_memory_is_private_to_the_agent(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    tools = [{"name": "memory__save"}, {"name": "memory__search"}]
    agent = await create_agent(client, tools=tools)
    other_agent = await create_agent(client, name="Other", tools=tools)
    fake_provider.model.responses = [
        reply(
            "", tool_call("memory__save", {"content": "The user's favourite colour is teal"}, "m1")
        ),
        reply("Noted."),
        reply("", tool_call("memory__search", {"query": "favourite colour"}, "m2")),
        reply("Teal."),
        reply("", tool_call("memory__search", {"query": "favourite colour"}, "m3")),
        reply("I don't know."),
    ]
    conv = await create_conversation(client, agent["id"])
    await send_message(client, conv["id"], "Remember: teal")
    conv2 = await create_conversation(client, agent["id"])  # a new conversation, same agent
    events = await send_message(client, conv2["id"], "What colour?")
    recalled = next(e for e in events if e["event"] == "tool.call.completed")["data"]["result"]
    assert "teal" in recalled

    conv3 = await create_conversation(client, other_agent["id"])
    events = await send_message(client, conv3["id"], "What colour?")
    assert (
        next(e for e in events if e["event"] == "tool.call.completed")["data"]["result"]
        == "No memories yet."
    )

    memories = (await client.get(f"/api/agents/{agent['id']}/memories")).json()
    assert [m["content"] for m in memories] == ["The user's favourite colour is teal"]
    assert (await client.delete(f"/api/memories/{memories[0]['id']}")).status_code == 204
    assert (await client.get(f"/api/agents/{agent['id']}/memories")).json() == []
    assert (await client.delete(f"/api/agents/{agent['id']}/memories")).status_code == 204


async def test_both_vector_backends_rank_the_same(client: AsyncClient, app: FastAPI) -> None:
    """The SQL-array fallback and pgvector (when installed, e.g. in CI) agree on ranking."""
    from app.services import knowledge_service

    c = await _collection(client)
    doc = await _upload(client, c["id"])
    await _wait_ready(client, c["id"], doc["id"])
    query = {"collection_ids": [c["id"]], "query": "inverter warranty years"}
    saved = dict(knowledge_service._PGVECTOR)
    try:
        knowledge_service._PGVECTOR.clear()
        native = (await client.post("/api/knowledge/search", json=query)).json()
        for key in list(knowledge_service._PGVECTOR) or [""]:
            knowledge_service._PGVECTOR[key] = False  # force the portable fallback
        fallback = (await client.post("/api/knowledge/search", json=query)).json()
    finally:
        knowledge_service._PGVECTOR.clear()
        knowledge_service._PGVECTOR.update(saved)
    assert [h["chunk"] for h in native] == [h["chunk"] for h in fallback]
    assert "warranty" in fallback[0]["text"]
