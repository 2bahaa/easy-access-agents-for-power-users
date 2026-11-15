"""Minimal MCP client (official `mcp` SDK, v2) for discovery and tool calls.

A session is opened per operation (initialize → list/call → close). That keeps workers
stateless and isolates failures; stdio servers are therefore started per call. Pooling is a
possible optimisation, not a correctness requirement.

Supported transports: `stdio` (a local command, admin-allow-listed) and `http`
(Streamable HTTP). Every operation is bounded by a timeout.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client  # the factory the SDK uses itself

MAX_RESULT_CHARS = 20_000
# Stdio servers' stderr is discarded (opened once; never read).
_DEVNULL = open(os.devnull, "w")  # noqa: SIM115


class McpError(Exception):
    """User-safe MCP failure (server unreachable, protocol error, tool error)."""


@dataclass(frozen=True)
class McpServerSpec:
    transport: Literal["stdio", "http"]
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    # Secrets already decrypted: env vars for stdio, HTTP headers for http.
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class McpToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]


def _minimal_env(extra: dict[str, str]) -> dict[str, str]:
    """Only what a child process needs to start, plus the server's declared variables —
    never the platform's own secrets (database URL, JWT secret, keys)."""
    keep = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "PYTHONIOENCODING")
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env.update(extra)
    return env


@contextlib.asynccontextmanager
async def _session(spec: McpServerSpec) -> AsyncIterator[ClientSession]:
    if spec.transport == "stdio":
        if not spec.command:
            raise McpError("No command configured for this MCP server")
        params = StdioServerParameters(
            command=spec.command, args=list(spec.args), env=_minimal_env(spec.env)
        )
        async with stdio_client(params, errlog=_DEVNULL) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                yield session
    else:
        if not spec.url:
            raise McpError("No URL configured for this MCP server")
        async with create_mcp_http_client(headers=spec.headers or None) as http:
            async with streamable_http_client(spec.url, http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    yield session


async def _bounded[T](coro: Any, timeout_s: float, what: str) -> T:
    try:
        result: T = await asyncio.wait_for(coro, timeout=timeout_s)
        return result
    except TimeoutError:
        raise McpError(f"MCP server did not respond to {what} within {timeout_s:g}s") from None
    except McpError:
        raise
    except BaseExceptionGroup as group:  # anyio task groups wrap transport failures
        inner = group.exceptions[0] if group.exceptions else group
        while isinstance(inner, BaseExceptionGroup) and inner.exceptions:
            inner = inner.exceptions[0]
        if isinstance(inner, McpError):
            raise inner from None
        raise McpError(f"MCP {what} failed: {type(inner).__name__}") from group
    except Exception as e:  # transport/protocol errors: user-safe summary only
        raise McpError(f"MCP {what} failed: {type(e).__name__}") from e


async def list_tools(spec: McpServerSpec, timeout_s: float = 20.0) -> list[McpToolInfo]:
    async def run() -> list[McpToolInfo]:
        async with _session(spec) as session:
            result = await session.list_tools()
            return [
                McpToolInfo(
                    name=t.name,
                    description=(t.description or "")[:1000],
                    input_schema=dict(t.input_schema or {"type": "object", "properties": {}}),
                )
                for t in result.tools
            ]

    return await _bounded(run(), timeout_s, "tool discovery")


def _content_text(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        kind = getattr(item, "type", "")
        if kind == "text":
            parts.append(str(getattr(item, "text", "")))
        else:  # images/audio/resources are not passed to text models
            parts.append(f"[{kind or 'binary'} content omitted]")
    structured = getattr(result, "structured_content", None)
    if not parts and structured is not None:
        parts.append(str(structured))
    text = "\n".join(parts)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f"… [{len(text) - MAX_RESULT_CHARS} more chars truncated]"
    return text


async def call_tool(
    spec: McpServerSpec, name: str, arguments: dict[str, Any], timeout_s: float
) -> str:
    async def run() -> str:
        async with _session(spec) as session:
            result = await session.call_tool(name, arguments)
        # Inspect after the session closed, so errors are not wrapped in task-group errors.
        text = _content_text(result)
        if getattr(result, "is_error", False):
            raise McpError(f"The tool reported an error: {text[:500]}")
        return text

    return await _bounded(run(), timeout_s, f"call to '{name}'")
