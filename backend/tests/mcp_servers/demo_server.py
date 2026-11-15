"""Deterministic MCP server for tests (official SDK). Run over stdio: `python demo_server.py`,
or over Streamable HTTP via `build().streamable_http_app()` (see test fixtures)."""

import asyncio
import os

from mcp.server.mcpserver import MCPServer


def build() -> MCPServer:
    server = MCPServer("demo")

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    @server.tool()
    def echo(text: str) -> str:
        """Return the text unchanged."""
        return text

    @server.tool()
    def secret_env() -> str:
        """Report whether the declared secret reached the server, and whether a platform
        secret leaked into its environment."""
        return f"token={os.environ.get('DEMO_TOKEN', 'unset')} leaked={'JWT_SECRET' in os.environ}"

    @server.tool()
    def fail() -> str:
        """Always fails."""
        raise ValueError("the demo tool failed on purpose")

    @server.tool()
    async def slow(seconds: float) -> str:
        """Sleep, then answer."""
        await asyncio.sleep(seconds)
        return "done"

    return server


if __name__ == "__main__":
    build().run("stdio")
