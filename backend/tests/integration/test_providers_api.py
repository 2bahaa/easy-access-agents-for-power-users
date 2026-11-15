from typing import Any

from httpx import AsyncClient

from tests.fakes import FakeProvider


async def test_list_providers(client: AsyncClient) -> None:
    (builtin,) = (await client.get("/api/providers")).json()
    assert (builtin["name"], builtin["available"], builtin["builtin"]) == ("ollama", True, True)
    assert builtin["kind"] == "ollama" and builtin["has_secret"] is False


async def test_list_models(client: AsyncClient) -> None:
    resp = await client.get("/api/providers/ollama/models")
    assert resp.status_code == 200
    assert {m["name"]: m["supports_tools"] for m in resp.json()} == {
        "fake-tools:1b": True,
        "fake-plain:1b": False,
    }


async def test_unknown_provider_404(client: AsyncClient) -> None:
    assert (await client.get("/api/providers/openai/models")).status_code == 404


async def test_provider_unavailable_502(client: AsyncClient, fake_provider: FakeProvider) -> None:
    fake_provider.available = False
    (builtin,) = (await client.get("/api/providers")).json()
    assert (builtin["name"], builtin["available"], builtin["status"]) == ("ollama", False, "error")
    resp = await client.get("/api/providers/ollama/models")
    assert resp.status_code == 502
    assert resp.json()["detail"] == "Ollama is not reachable"


def payload(**overrides: Any) -> dict[str, Any]:
    return {"name": "A", "model": "tools:1b", "tools": [{"name": "calculator"}]} | overrides


async def test_agent_with_unknown_provider_is_422(client: AsyncClient) -> None:
    resp = await client.post("/api/agents", json=payload(provider="openai"))
    assert resp.status_code == 422
    assert "Unknown provider" in resp.json()["detail"]


async def test_tools_on_non_tool_model_is_409(client: AsyncClient) -> None:
    resp = await client.post("/api/agents", json=payload(model="plain:1b"))
    assert resp.status_code == 409
    assert "does not support tool calling" in resp.json()["detail"]
    # Without tools the same model is fine.
    assert (
        await client.post("/api/agents", json=payload(model="plain:1b", tools=[]))
    ).status_code == 201


async def test_unknown_capability_allows_save(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    fake_provider.missing_models.add("not-pulled:7b")
    resp = await client.post("/api/agents", json=payload(model="not-pulled:7b"))
    assert resp.status_code == 201  # enforced later by the run pre-flight check
