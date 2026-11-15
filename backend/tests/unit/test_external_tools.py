"""Custom HTTP tool execution and MCP client hardening (no network)."""

import json
import os

import httpx
import pytest

from app.tools.base import EmptyConfig, ToolContext, ToolError
from app.tools.external import (
    UNTRUSTED_PREFIX,
    HttpParam,
    HttpTool,
    McpTool,
    ToolArgsError,
    check_outbound_url,
)
from app.tools.mcp_client import McpServerSpec, _minimal_env

CTX = ToolContext(workspace_dir=__import__("pathlib").Path("."))


def make_tool(handler, **kw):  # type: ignore[no-untyped-def]
    return HttpTool(
        name="http__weather",
        description="d",
        method=kw.pop("method", "GET"),
        url_template=kw.pop("url", "https://api.example.test/weather/{city}"),
        params=kw.pop(
            "params",
            [
                HttpParam("city", "string", "path"),
                HttpParam("units", "string", "query", required=False),
            ],
        ),
        allowed_hosts=["api.example.test"],
        headers={"X-Api-Key": "k"},
        transport=httpx.MockTransport(handler),
        **kw,
    )


@pytest.fixture(autouse=True)
def _resolve_test_host(monkeypatch: pytest.MonkeyPatch) -> None:
    real = __import__("socket").getaddrinfo

    def fake(host: str, *a, **k):  # type: ignore[no-untyped-def]
        if host.endswith(".test"):
            return [(2, 1, 6, "", ("93.184.216.34", 0))]
        return real(host, *a, **k)

    monkeypatch.setattr("socket.getaddrinfo", fake)


async def test_http_tool_builds_request_and_marks_output() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"temp": 31, "city": "Cairo"})

    tool = make_tool(handler)
    args = tool.parse_args({"city": "Cairo City", "units": "metric"})
    out = await tool.run(args, EmptyConfig(), CTX)
    assert str(seen[0].url) == "https://api.example.test/weather/Cairo%20City?units=metric"
    assert seen[0].headers["x-api-key"] == "k"
    assert out.startswith(UNTRUSTED_PREFIX) and json.loads(out[len(UNTRUSTED_PREFIX) :]) == {
        "temp": 31,
        "city": "Cairo",
    }


async def test_http_tool_post_body_and_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content) == {"q": "bad"}:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text="x" * 300_000)

    tool = make_tool(
        handler,
        method="POST",
        url="https://api.example.test/search",
        params=[HttpParam("q", "string", "body")],
    )
    with pytest.raises(ToolError, match="HTTP 404"):
        await tool.run({"q": "bad"}, EmptyConfig(), CTX)
    out = await tool.run({"q": "ok"}, EmptyConfig(), CTX)
    assert out.endswith("[response truncated]") and len(out) < 210_000


def test_json_schema_validation() -> None:
    tool = make_tool(lambda r: httpx.Response(200))
    with pytest.raises(ToolArgsError):
        tool.parse_args({})  # city required
    with pytest.raises(ToolArgsError):
        tool.parse_args({"city": "x", "extra": 1})  # additionalProperties: false
    with pytest.raises(ToolArgsError):
        tool.parse_args({"city": 5})


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/x",
        "ftp://api.example.test/x",
        "http://169.254.169.254/latest",
        "https://api.example.test.evil.test/x",
    ],
)
def test_outbound_url_guard(url: str) -> None:
    with pytest.raises(ToolError):
        check_outbound_url(url, ["api.example.test"])


def test_wildcard_hosts() -> None:
    check_outbound_url("https://a.allowed.test/x", ["*.allowed.test"])
    with pytest.raises(ToolError):
        check_outbound_url("https://allowed.test.evil.test/x", ["*.allowed.test"])


def test_mcp_child_environment_is_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "x")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", "k")
    env = _minimal_env({"DEMO_TOKEN": "t"})
    assert env["DEMO_TOKEN"] == "t"
    assert not {"JWT_SECRET", "DATABASE_URL", "SECRET_ENCRYPTION_KEY"} & set(env)
    assert "PATH" in env or "Path" in env or not os.environ.get("PATH")


def test_mcp_tool_function_schema() -> None:
    tool = McpTool(
        name="mcp__demo__add",
        description="Add",
        server=McpServerSpec(transport="stdio"),
        remote_name="add",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "required": ["a"],
        },
    )
    schema = tool.to_function_schema()["function"]
    assert schema["name"] == "mcp__demo__add" and schema["parameters"]["required"] == ["a"]
    assert tool.parse_config({}) == EmptyConfig()
