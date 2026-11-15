"""MCP servers and custom HTTP tools end to end, against a real MCP server (official SDK)
over stdio and Streamable HTTP. Agents call them through the normal ToolNode checks."""

import asyncio
import contextlib
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.runtime.providers.registry import ProviderRegistry
from tests.conftest import UserClientFactory, register_user
from tests.fakes import FakeProvider, reply, tool_call
from tests.mcp_servers.demo_server import build as build_demo
from tests.sse_helpers import create_agent, create_conversation, send_message

DEMO = str(Path(__file__).resolve().parents[1] / "mcp_servers" / "demo_server.py")


async def _register(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {
        "name": "Demo",
        "slug": "demo",
        "transport": "stdio",
        "command": sys.executable,
        "args": [DEMO],
        "env": {"DEMO_TOKEN": "s3cret-token"},
        "timeout_s": 20,
    } | overrides
    resp = await client.post("/api/mcp-servers", json=body)
    assert resp.status_code == 201, resp.text
    server: dict[str, Any] = resp.json()
    return server


async def _discover_and_enable(client: AsyncClient, server_id: str, *tools: str) -> dict[str, Any]:
    resp = await client.post(f"/api/mcp-servers/{server_id}/refresh")
    assert resp.status_code == 200, resp.text
    for name in tools:
        r = await client.put(f"/api/mcp-servers/{server_id}/tools/{name}", json={"enabled": True})
        assert r.status_code == 200
    result: dict[str, Any] = resp.json()
    return result


def _tool_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e["event"] in ("tool.call.completed", "tool.call.failed")]


async def test_register_discover_enable_and_call_over_stdio(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    server = await _register(client)
    assert server["secret_keys"] == ["DEMO_TOKEN"] and "s3cret" not in str(server)
    result = await _discover_and_enable(client, server["id"])
    tools = {t["name"]: t for t in result["server"]["tools"]}
    assert set(tools) == {"add", "echo", "secret_env", "fail", "slow"}
    assert all(not t["enabled"] for t in tools.values())  # imported disabled
    assert result["server"]["status"] == "ok"
    # Disabled tools are neither listed nor grantable.
    assert not [t for t in (await client.get("/api/tools")).json() if t["source"] == "mcp"]
    resp = await client.post(
        "/api/agents",
        json={"name": "a", "model": "tools:1b", "tools": [{"name": "mcp__demo__add"}]},
    )
    assert resp.status_code == 422

    await client.put(f"/api/mcp-servers/{server['id']}/tools/add", json={"enabled": True})
    await client.put(f"/api/mcp-servers/{server['id']}/tools/secret_env", json={"enabled": True})
    listed = {t["name"]: t for t in (await client.get("/api/tools")).json()}
    assert listed["mcp__demo__add"]["source"] == "mcp"
    assert listed["mcp__demo__add"]["args_schema"]["required"] == ["a", "b"]

    agent = await create_agent(
        client, tools=[{"name": "mcp__demo__add"}, {"name": "mcp__demo__secret_env"}]
    )
    fake_provider.model.responses = [
        reply(
            "",
            tool_call("mcp__demo__add", {"a": 2, "b": 40}, "c1"),
            tool_call("mcp__demo__secret_env", {}, "c2"),
        ),
        reply("42"),
    ]
    conv = await create_conversation(client, agent["id"])
    events = await send_message(client, conv["id"], "add")
    done = _tool_events(events)
    assert [e["event"] for e in done] == ["tool.call.completed", "tool.call.completed"]
    assert done[0]["data"]["result"].endswith("42")
    assert done[0]["data"]["result"].startswith("[External tool output")  # untrusted marker
    assert "token=s3cret-token" in done[1]["data"]["result"]
    # Only granted tools are bound to the model.
    bound = {t["function"]["name"] for t in fake_provider.model.bound_tools or []}
    assert bound == {"mcp__demo__add", "mcp__demo__secret_env"}


async def test_argument_validation_errors_and_timeouts(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    server = await _register(client)
    await _discover_and_enable(client, server["id"], "add", "fail")
    tight = await _register(client, slug="tight", timeout_s=1)  # every call exceeds 1 s
    await _discover_and_enable(client, tight["id"], "slow")
    agent = await create_agent(
        client,
        tools=[
            {"name": "mcp__demo__add"},
            {"name": "mcp__demo__fail"},
            {"name": "mcp__tight__slow"},
        ],
    )
    fake_provider.model.responses = [
        reply(
            "",
            tool_call("mcp__demo__add", {"a": "two", "b": 1}, "v"),  # schema violation
            tool_call("mcp__demo__fail", {}, "f"),
            tool_call("mcp__tight__slow", {"seconds": 5}, "s"),
        ),
        reply("done"),
    ]
    conv = await create_conversation(client, agent["id"])
    failed = _tool_events(await send_message(client, conv["id"], "go"))
    by_id = {e["data"]["call_id"]: e for e in failed}
    assert (by_id["v"]["event"], by_id["v"]["data"]["kind"]) == ("tool.call.failed", "validation")
    assert (by_id["f"]["event"], by_id["f"]["data"]["kind"]) == ("tool.call.failed", "execution")
    assert "reported an error" in by_id["f"]["data"]["error"]
    assert by_id["s"]["event"] == "tool.call.failed"
    assert by_id["s"]["data"]["kind"] in ("timeout", "execution")  # ToolNode or client bound


async def test_disabling_a_tool_revokes_it_at_run_time(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    server = await _register(client)
    await _discover_and_enable(client, server["id"], "echo")
    agent = await create_agent(client, tools=[{"name": "mcp__demo__echo"}])
    await client.put(f"/api/mcp-servers/{server['id']}/tools/echo", json={"enabled": False})
    fake_provider.model.responses = [
        reply("", tool_call("mcp__demo__echo", {"text": "hi"}, "e")),
        reply("ok"),
    ]
    conv = await create_conversation(client, agent["id"])
    (event,) = _tool_events(await send_message(client, conv["id"], "echo"))
    assert (event["event"], event["data"]["kind"]) == ("tool.call.failed", "permission")
    # Deleting a server with grants is blocked.
    assert (await client.delete(f"/api/mcp-servers/{server['id']}")).status_code == 409


async def test_registration_rules_and_isolation(
    client: AsyncClient, make_client: UserClientFactory, settings: Settings
) -> None:
    bad = await client.post(
        "/api/mcp-servers",
        json={
            "name": "x",
            "slug": "x",
            "transport": "stdio",
            "command": "rm",
            "args": ["-rf", "/"],
        },
    )
    assert bad.status_code == 422 and "not allowed" in bad.json()["detail"]
    meta = await client.post(
        "/api/mcp-servers",
        json={"name": "m", "slug": "m", "transport": "http", "url": "http://169.254.169.254/mcp"},
    )
    assert meta.status_code == 422
    assert (
        await client.post(
            "/api/mcp-servers",
            json={
                "name": "y",
                "slug": "Bad Slug",
                "transport": "http",
                "url": "http://127.0.0.1:1/mcp",
            },
        )
    ).status_code == 422
    server = await _register(client)
    assert (
        await client.post(
            "/api/mcp-servers",
            json={
                "name": "dup",
                "slug": "demo",
                "transport": "http",
                "url": "http://127.0.0.1:1/mcp",
            },
        )
    ).status_code == 409

    other = await make_client("other@example.com")
    assert (await other.get("/api/mcp-servers")).json() == []
    assert (await other.post(f"/api/mcp-servers/{server['id']}/refresh")).status_code == 404
    editor = await make_client("editor@example.com")
    await client.post("/api/members", json={"email": "editor@example.com", "role": "editor"})
    editor.headers["X-Workspace-Id"] = (await client.get("/api/auth/me")).json()[
        "current_workspace_id"
    ]
    assert (await editor.post(f"/api/mcp-servers/{server['id']}/refresh")).status_code == 403
    assert (
        await editor.put(f"/api/mcp-servers/{server['id']}/tools/add", json={"enabled": True})
    ).status_code == 403


async def test_stdio_is_disabled_without_allow_list(settings: Settings, clean_db: None) -> None:
    app = create_app(
        settings.model_copy(update={"mcp_stdio_allowed_commands": ""}),
        provider_registry=ProviderRegistry([FakeProvider()]),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.headers["Authorization"] = f"Bearer {await register_user(c, 'a@example.com')}"
            resp = await c.post(
                "/api/mcp-servers",
                json={
                    "name": "x",
                    "slug": "x",
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": [DEMO],
                },
            )
            assert resp.status_code == 422 and "disabled" in resp.json()["detail"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
async def http_mcp() -> AsyncIterator[str]:
    """The demo server over Streamable HTTP on a local port."""
    port = _free_port()
    config = uvicorn.Config(
        build_demo().streamable_http_app(), host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    with contextlib.suppress(Exception):
        await asyncio.wait_for(task, timeout=5)


async def test_streamable_http_transport(
    client: AsyncClient, fake_provider: FakeProvider, http_mcp: str
) -> None:
    server = await _register(
        client,
        slug="web",
        transport="http",
        url=http_mcp,
        command=None,
        args=[],
        env={},
        headers={"Authorization": "Bearer header-secret"},
    )
    assert server["secret_keys"] == ["Authorization"] and "header-secret" not in str(server)
    result = await _discover_and_enable(client, server["id"], "echo")
    assert result["server"]["status"] == "ok" and len(result["server"]["tools"]) == 5
    agent = await create_agent(client, tools=[{"name": "mcp__web__echo"}])
    fake_provider.model.responses = [
        reply("", tool_call("mcp__web__echo", {"text": "over http"}, "h")),
        reply("ok"),
    ]
    conv = await create_conversation(client, agent["id"])
    (event,) = _tool_events(await send_message(client, conv["id"], "echo"))
    assert event["event"] == "tool.call.completed" and event["data"]["result"].endswith("over http")


async def test_unreachable_server_records_error(client: AsyncClient) -> None:
    server = await _register(
        client,
        slug="down",
        transport="http",
        url=f"http://127.0.0.1:{_free_port()}/mcp",
        command=None,
        args=[],
        env={},
        timeout_s=3,
    )
    resp = await client.post(f"/api/mcp-servers/{server['id']}/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["server"]["status"] == "error" and body["warnings"]


# ---- custom HTTP tools --------------------------------------------------------------------


async def test_custom_http_tool_rules_and_grant(
    client: AsyncClient, fake_provider: FakeProvider, make_client: UserClientFactory
) -> None:
    base = {
        "slug": "weather",
        "description": "Current weather",
        "method": "GET",
        "url_template": "https://api.example.test/weather/{city}",
        "params": [
            {"name": "city", "type": "string", "location": "path"},
            {"name": "units", "type": "string", "location": "query", "required": False},
        ],
        "headers": {"X-Api-Key": "hidden-key"},
    }
    assert (
        await client.post("/api/custom-tools", json=base | {"url_template": "https://evil.test/x"})
    ).status_code == 422
    assert (
        await client.post("/api/custom-tools", json=base | {"url_template": "https://{host}/x"})
    ).status_code == 422
    unused = base | {"params": [{"name": "zip", "location": "path"}]}
    assert (await client.post("/api/custom-tools", json=unused)).status_code == 422
    resp = await client.post("/api/custom-tools", json=base)
    assert resp.status_code == 201, resp.text
    tool = resp.json()
    assert tool["tool_name"] == "http__weather" and tool["header_keys"] == ["X-Api-Key"]
    assert "hidden-key" not in resp.text

    listed = {t["name"]: t for t in (await client.get("/api/tools")).json()}
    assert listed["http__weather"]["source"] == "http"
    assert listed["http__weather"]["args_schema"]["required"] == ["city"]
    agent = await create_agent(client, tools=[{"name": "http__weather"}])
    # The host is allow-listed but does not resolve here: the call fails safely inside the tool.
    fake_provider.model.responses = [
        reply("", tool_call("http__weather", {"city": "Cairo"}, "w")),
        reply("ok"),
    ]
    conv = await create_conversation(client, agent["id"])
    (event,) = _tool_events(await send_message(client, conv["id"], "weather"))
    assert event["event"] == "tool.call.failed" and event["data"]["kind"] == "execution"

    other = await make_client("x@example.com")
    resp = await other.post(
        "/api/agents", json={"name": "a", "model": "tools:1b", "tools": [{"name": "http__weather"}]}
    )
    assert resp.status_code == 422
    assert (await client.delete(f"/api/custom-tools/{tool['id']}")).status_code == 409


async def test_custom_tools_disabled_without_allow_list(settings: Settings, clean_db: None) -> None:
    app = create_app(
        settings.model_copy(update={"custom_tool_allowed_hosts": ""}),
        provider_registry=ProviderRegistry([FakeProvider()]),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.headers["Authorization"] = f"Bearer {await register_user(c, 'b@example.com')}"
            resp = await c.post(
                "/api/custom-tools",
                json={
                    "slug": "t",
                    "description": "d",
                    "url_template": "https://api.example.test/x",
                },
            )
            assert resp.status_code == 422 and "disabled" in resp.json()["detail"]
