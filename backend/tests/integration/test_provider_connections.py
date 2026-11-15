"""Provider connections: credentials, isolation, RBAC, agents on connections, capability
overrides and the live tool-calling probe (connections resolve to a fake provider)."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, ProviderConnection
from tests.conftest import UserClientFactory
from tests.fakes import FakeProvider, reply, tool_call
from tests.sse_helpers import create_conversation, send_message

KEY = "sk-test-0123456789abcd"


async def _connection(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {"name": "OpenAI", "kind": "openai", "api_key": KEY} | overrides
    resp = await client.post("/api/providers", json=body)
    assert resp.status_code == 201, resp.text
    conn: dict[str, Any] = resp.json()
    return conn


async def test_credentials_are_encrypted_and_never_returned(
    client: AsyncClient, session: AsyncSession, cloud_provider: FakeProvider
) -> None:
    conn = await _connection(client)
    assert conn["has_secret"] is True and conn["secret_hint"] == "…abcd"
    assert conn["builtin"] is False and conn["kind"] == "openai" and conn["name"] == conn["id"]
    for resp in (
        await client.get("/api/providers"),
        await client.post(f"/api/providers/{conn['id']}/test"),
        await client.get(f"/api/providers/{conn['id']}/models"),
    ):
        assert KEY not in resp.text
    row = await session.scalar(select(ProviderConnection))
    assert row is not None and row.secret_enc and KEY not in row.secret_enc
    # The decrypted key only reaches the provider factory (in memory).
    assert cloud_provider.specs[-1].api_key == KEY
    actions = list(await session.scalars(select(AuditLog.action)))
    assert "provider.created" in actions


async def test_validation_of_connections(client: AsyncClient) -> None:
    assert (
        await client.post("/api/providers", json={"name": "x", "kind": "openai"})
    ).status_code == 422
    resp = await client.post("/api/providers", json={"name": "x", "kind": "openai_compatible"})
    assert resp.status_code == 422  # base URL required
    resp = await client.post(
        "/api/providers",
        json={"name": "meta", "kind": "openai_compatible", "base_url": "http://169.254.169.254/v1"},
    )
    assert resp.status_code == 422
    await _connection(client)
    assert (
        await client.post(
            "/api/providers", json={"name": "OpenAI", "kind": "openai", "api_key": KEY}
        )
    ).status_code == 409
    local = await _connection(
        client,
        name="LM Studio",
        kind="openai_compatible",
        base_url="http://127.0.0.1:1234/v1",
        api_key=None,
    )
    assert local["has_secret"] is False and local["base_url"] == "http://127.0.0.1:1234/v1"


async def test_update_and_remove_key(client: AsyncClient) -> None:
    conn = await _connection(client)
    resp = await client.patch(
        f"/api/providers/{conn['id']}", json={"api_key": "sk-new-key-99998888"}
    )
    assert resp.json()["secret_hint"] == "…8888" and resp.json()["status"] == "unknown"
    # OpenAI requires a key: removing it is rejected; a compatible endpoint allows it.
    assert (
        await client.patch(f"/api/providers/{conn['id']}", json={"api_key": ""})
    ).status_code == 422
    local = await _connection(
        client, name="vLLM", kind="openai_compatible", base_url="http://127.0.0.1:8000/v1"
    )
    resp = await client.patch(f"/api/providers/{local['id']}", json={"api_key": ""})
    assert resp.status_code == 200 and resp.json()["has_secret"] is False


async def test_secrets_require_server_key(client: AsyncClient, app: Any) -> None:
    from app.crypto import SecretBox

    app.state.provider_resolver.secrets = SecretBox("")  # server without SECRET_ENCRYPTION_KEY
    resp = await client.post("/api/providers", json={"name": "x", "kind": "openai", "api_key": KEY})
    assert resp.status_code == 422 and "SECRET_ENCRYPTION_KEY" in resp.json()["detail"]


async def test_connections_are_workspace_scoped_and_admin_only(
    client: AsyncClient, make_client: UserClientFactory
) -> None:
    conn = await _connection(client)
    other = await make_client("other@example.com")
    assert [p["name"] for p in (await other.get("/api/providers")).json()] == ["ollama"]
    for method, path in (
        ("GET", f"/api/providers/{conn['id']}/models"),
        ("POST", f"/api/providers/{conn['id']}/test"),
        ("PATCH", f"/api/providers/{conn['id']}"),
        ("DELETE", f"/api/providers/{conn['id']}"),
    ):
        resp = await other.request(method, path, json={} if method == "PATCH" else None)
        assert resp.status_code == 404, (method, path)
    # Agents cannot reference another workspace's connection.
    resp = await other.post(
        "/api/agents", json={"name": "a", "model": "cloud-model", "connection_id": conn["id"]}
    )
    assert resp.status_code == 422

    editor = await make_client("editor@example.com")
    await client.post("/api/members", json={"email": "editor@example.com", "role": "editor"})
    editor.headers["X-Workspace-Id"] = (await client.get("/api/auth/me")).json()[
        "current_workspace_id"
    ]
    resp = await editor.post("/api/providers", json={"name": "e", "kind": "openai", "api_key": KEY})
    assert resp.status_code == 403
    assert (await editor.delete(f"/api/providers/{conn['id']}")).status_code == 403
    assert (await editor.get(f"/api/providers/{conn['id']}/models")).status_code == 200


async def test_agent_on_connection_with_capability_override(
    client: AsyncClient, cloud_provider: FakeProvider
) -> None:
    conn = await _connection(client)
    models = {
        m["name"]: m for m in (await client.get(f"/api/providers/{conn['id']}/models")).json()
    }
    assert (
        models["cloud-model"]["supports_tools"] is None
        and models["cloud-model"]["tools_source"] is None
    )

    # Ollama-only parameters are rejected for other kinds.
    resp = await client.post(
        "/api/agents",
        json={
            "name": "c",
            "model": "cloud-model",
            "connection_id": conn["id"],
            "model_params": {"num_ctx": 4096},
        },
    )
    assert resp.status_code == 422 and "only apply to Ollama" in resp.json()["detail"]

    resp = await client.post(
        "/api/agents",
        json={
            "name": "Cloud agent",
            "model": "cloud-model",
            "connection_id": conn["id"],
            "tools": [{"name": "calculator"}],
            "model_params": {"temperature": 0.1, "max_tokens": 300},
        },
    )
    assert resp.status_code == 201, resp.text  # unknown tool support: saving is allowed…
    agent = resp.json()
    assert agent["provider"] == "openai" and agent["connection_id"] == conn["id"]

    conv = await create_conversation(client, agent["id"])
    events = await send_message(client, conv["id"], "2+2?")
    assert events[-1]["event"] == "run.failed"  # …but running refuses until it is confirmed
    assert events[-1]["data"]["code"] == "model_no_tool_support"
    assert "does not report" in events[-1]["data"]["message"]

    resp = await client.put(
        f"/api/providers/{conn['id']}/models/cloud-model/capabilities",
        json={"supports_tools": True},
    )
    assert resp.status_code == 204
    models = {
        m["name"]: m for m in (await client.get(f"/api/providers/{conn['id']}/models")).json()
    }
    assert (models["cloud-model"]["supports_tools"], models["cloud-model"]["tools_source"]) == (
        True,
        "user",
    )

    cloud_provider.model.responses = [
        reply("", tool_call("calculator", {"expression": "2+2"}, "c1")),
        reply("4"),
    ]
    events = await send_message(client, conv["id"], "2+2?")
    assert events[-1]["event"] == "run.completed"
    assert cloud_provider.created[-1] == ("cloud-model", {"temperature": 0.1, "max_tokens": 300})

    # A connection in use cannot be deleted.
    assert (await client.delete(f"/api/providers/{conn['id']}")).status_code == 409
    await client.delete(f"/api/agents/{agent['id']}")
    assert (await client.delete(f"/api/providers/{conn['id']}")).status_code == 204


async def test_live_probe_records_tool_support(
    client: AsyncClient, cloud_provider: FakeProvider
) -> None:
    conn = await _connection(client)
    cloud_provider.model.responses = [reply("", tool_call("ping", {}, "p1"))]
    resp = await client.post(f"/api/providers/{conn['id']}/models/cloud-model/probe")
    assert resp.status_code == 200 and resp.json()["supports_tools"] is True
    models = {
        m["name"]: m for m in (await client.get(f"/api/providers/{conn['id']}/models")).json()
    }
    assert models["cloud-model"]["tools_source"] == "probe"
    assert (
        cloud_provider.model.bound_tools
        and cloud_provider.model.bound_tools[0]["function"]["name"] == "ping"
    )

    cloud_provider.model.responses = [reply("I cannot call tools.")]
    resp = await client.post(f"/api/providers/{conn['id']}/models/cloud-model/probe")
    assert resp.json()["supports_tools"] is False
    # Clearing the override returns to "unknown".
    await client.put(
        f"/api/providers/{conn['id']}/models/cloud-model/capabilities",
        json={"supports_tools": None},
    )
    models = {
        m["name"]: m for m in (await client.get(f"/api/providers/{conn['id']}/models")).json()
    }
    assert models["cloud-model"]["supports_tools"] is None


async def test_provider_reported_capabilities_win_over_overrides(client: AsyncClient) -> None:
    # Built-in fake Ollama reports tools=False for fake-plain:1b: an override cannot flip it.
    await client.put(
        "/api/providers/ollama/models/fake-plain:1b/capabilities", json={"supports_tools": True}
    )
    models = {m["name"]: m for m in (await client.get("/api/providers/ollama/models")).json()}
    assert (models["fake-plain:1b"]["supports_tools"], models["fake-plain:1b"]["tools_source"]) == (
        False,
        "provider",
    )
