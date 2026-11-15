"""Runtime-defined tools: MCP servers (discovery, enable/disable, health) and custom HTTP
tools. Also the bridge to runs: grant validation and per-run tool construction.

Security model:
* Only admins register servers/tools. Stdio servers must use an allow-listed command
  (`MCP_STDIO_ALLOWED_COMMANDS`, empty = stdio disabled) and get a minimal environment.
* HTTP MCP URLs pass the provider SSRF guard; custom HTTP tools may only call
  `CUSTOM_TOOL_ALLOWED_HOSTS`.
* Discovered MCP tools are imported **disabled**; an admin enables each one, and each agent
  must still be granted it. Every call goes through the ToolNode checks.
* Secrets (env vars, headers) are encrypted at rest and decrypted only in memory.
"""

import json
import re
import uuid
from collections.abc import Sequence
from pathlib import PurePath
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.crypto import SecretBox, SecretDecryptionError, SecretsNotConfiguredError
from app.db.models import AgentTool, CustomTool, McpServer, McpTool
from app.schemas.capabilities import (
    CustomToolWrite,
    McpServerCreate,
    McpServerUpdate,
)
from app.services import audit_service
from app.services.errors import ConflictError, DomainValidationError, NotFoundError
from app.services.principal import Principal
from app.services.provider_service import validate_base_url
from app.tools.base import ToolLike
from app.tools.external import (
    TOOL_NAME_RE,
    HttpParam,
    HttpTool,
    http_tool_name,
    mcp_tool_name,
)
from app.tools.external import (
    McpTool as McpRuntimeTool,
)
from app.tools.mcp_client import McpError, McpServerSpec, McpToolInfo, list_tools

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


def _encrypt_json(secrets: SecretBox, data: dict[str, Any]) -> str | None:
    if not data:
        return None
    try:
        return secrets.encrypt(json.dumps(data))
    except SecretsNotConfiguredError as e:
        raise DomainValidationError(str(e)) from e


def _decrypt_json(secrets: SecretBox, token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    try:
        value: dict[str, Any] = json.loads(secrets.decrypt(token))
        return value
    except (SecretsNotConfiguredError, SecretDecryptionError) as e:
        raise NotFoundError(
            "Stored secrets cannot be decrypted on this server; re-enter them"
        ) from e


# ---- MCP servers ------------------------------------------------------------------------


def _check_transport(
    settings: Settings, transport: str, command: str | None, url: str | None
) -> str | None:
    if transport == "stdio":
        if not command:
            raise DomainValidationError("A command is required for stdio servers")
        allowed = settings.mcp_stdio_commands
        if not allowed:
            raise DomainValidationError(
                "Stdio MCP servers are disabled on this server "
                "(MCP_STDIO_ALLOWED_COMMANDS is empty)"
            )
        if command not in allowed and PurePath(command).name not in allowed:
            raise DomainValidationError(
                f"Command '{command}' is not allowed; allowed: {', '.join(allowed)}"
            )
        return None
    if not url:
        raise DomainValidationError("A URL is required for HTTP servers")
    return validate_base_url(url, settings)


async def get_server(
    session: AsyncSession, workspace_id: uuid.UUID, server_id: uuid.UUID
) -> McpServer:
    server = await session.get(McpServer, server_id, populate_existing=True)
    if server is None or server.workspace_id != workspace_id:
        raise NotFoundError(f"MCP server {server_id} not found")
    return server


def server_spec(secrets: SecretBox, server: McpServer) -> McpServerSpec:
    data = _decrypt_json(secrets, server.secrets_enc)
    return McpServerSpec(
        transport=server.transport,  # type: ignore[arg-type]
        command=server.command,
        args=[str(a) for a in server.args],
        url=server.url,
        env={str(k): str(v) for k, v in (data.get("env") or {}).items()},
        headers={str(k): str(v) for k, v in (data.get("headers") or {}).items()},
    )


async def list_servers(session: AsyncSession, principal: Principal) -> Sequence[McpServer]:
    stmt = select(McpServer).where(McpServer.workspace_id == principal.workspace_id)
    return (await session.scalars(stmt.order_by(McpServer.name))).all()


async def server_tools(session: AsyncSession, server_id: uuid.UUID) -> Sequence[McpTool]:
    stmt = select(McpTool).where(McpTool.server_id == server_id).order_by(McpTool.name)
    return (await session.scalars(stmt)).all()


async def create_server(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    secrets: SecretBox,
    data: McpServerCreate,
) -> McpServer:
    principal.require("admin")
    if not SLUG_RE.match(data.slug):
        raise DomainValidationError("Slug: 1-31 lowercase letters, digits or '-'")
    url = _check_transport(settings, data.transport, data.command, data.url)
    if await session.scalar(
        select(McpServer.id).where(
            McpServer.workspace_id == principal.workspace_id, McpServer.slug == data.slug
        )
    ):
        raise ConflictError(f"An MCP server with slug '{data.slug}' already exists")
    server = McpServer(
        workspace_id=principal.workspace_id,
        name=data.name,
        slug=data.slug,
        transport=data.transport,
        command=data.command if data.transport == "stdio" else None,
        args=data.args if data.transport == "stdio" else [],
        url=url,
        secrets_enc=_encrypt_json(
            secrets,
            {"env": data.env, "headers": data.headers} if (data.env or data.headers) else {},
        ),
        secret_keys=sorted([*data.env, *data.headers]),
        timeout_s=data.timeout_s,
        enabled=True,
    )
    session.add(server)
    await session.flush()
    audit_service.record(
        session,
        "mcp.server_registered",
        principal=principal,
        target_type="mcp_server",
        target_id=server.id,
        transport=data.transport,
        name=data.name,
    )
    await session.commit()
    return server


async def update_server(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    secrets: SecretBox,
    server_id: uuid.UUID,
    data: McpServerUpdate,
) -> McpServer:
    principal.require("admin")
    server = await get_server(session, principal.workspace_id, server_id)
    if data.name is not None:
        server.name = data.name
    if data.enabled is not None:
        server.enabled = data.enabled
    if data.timeout_s is not None:
        server.timeout_s = data.timeout_s
    if data.command is not None or data.args is not None or data.url is not None:
        command = data.command if data.command is not None else server.command
        url = data.url if data.url is not None else server.url
        server.url = _check_transport(settings, server.transport, command, url)
        if server.transport == "stdio":
            server.command = command
            server.args = data.args if data.args is not None else server.args
    if data.env is not None or data.headers is not None:
        current = _decrypt_json(secrets, server.secrets_enc)
        env = data.env if data.env is not None else current.get("env", {})
        headers = data.headers if data.headers is not None else current.get("headers", {})
        server.secrets_enc = _encrypt_json(
            secrets, {"env": env, "headers": headers} if (env or headers) else {}
        )
        server.secret_keys = sorted([*env, *headers])
    server.status = "unknown"
    audit_service.record(
        session,
        "mcp.server_updated",
        principal=principal,
        target_type="mcp_server",
        target_id=server.id,
    )
    await session.commit()
    return await get_server(session, principal.workspace_id, server_id)


async def delete_server(session: AsyncSession, principal: Principal, server_id: uuid.UUID) -> None:
    principal.require("admin")
    server = await get_server(session, principal.workspace_id, server_id)
    prefix = f"mcp__{server.slug}__"
    used = await session.scalar(
        select(func.count()).select_from(AgentTool).where(AgentTool.tool_name.startswith(prefix))
    )
    if used:
        raise ConflictError(f"{used} agent tool grant(s) use this server; remove them first")
    await session.delete(server)
    audit_service.record(
        session,
        "mcp.server_deleted",
        principal=principal,
        target_type="mcp_server",
        target_id=server_id,
    )
    await session.commit()


async def refresh_server(
    session: AsyncSession, principal: Principal, secrets: SecretBox, server_id: uuid.UUID
) -> tuple[McpServer, list[str]]:
    """Discover tools. New tools are added disabled; vanished tools are removed; schemas and
    descriptions update in place. Returns warnings for skipped tools."""
    principal.require("admin")
    server = await get_server(session, principal.workspace_id, server_id)
    warnings: list[str] = []
    try:
        # Discovery includes process start-up (stdio): give it at least 20 s.
        discovered = await list_tools(
            server_spec(secrets, server), timeout_s=max(20.0, float(server.timeout_s))
        )
    except McpError as e:
        server.status, server.last_error, server.last_checked_at = "error", str(e), func.now()
        await session.commit()
        return await get_server(session, principal.workspace_id, server_id), [str(e)]
    valid: dict[str, McpToolInfo] = {}
    for t in discovered:
        full = mcp_tool_name(server.slug, t.name)
        if not TOOL_NAME_RE.match(t.name) or len(full) > 64:
            warnings.append(
                f"Skipped '{t.name[:80]}': MCP tool names must be [a-zA-Z0-9_-] and the full "
                f"name '{full[:80]}' at most 64 characters"
            )
            continue
        valid[t.name] = t
    existing = {t.name: t for t in await server_tools(session, server.id)}
    for name, info in valid.items():
        row = existing.get(name)
        if row is None:
            session.add(
                McpTool(
                    server_id=server.id,
                    name=name,
                    description=info.description,
                    input_schema=info.input_schema,
                    enabled=False,
                )
            )
        else:
            row.description, row.input_schema = info.description, info.input_schema
    gone = [n for n in existing if n not in valid]
    if gone:
        await session.execute(
            delete(McpTool).where(McpTool.server_id == server.id, McpTool.name.in_(gone))
        )
    server.status, server.last_error, server.last_checked_at = "ok", None, func.now()
    audit_service.record(
        session,
        "mcp.tools_discovered",
        principal=principal,
        target_type="mcp_server",
        target_id=server.id,
        count=len(valid),
    )
    await session.commit()
    return await get_server(session, principal.workspace_id, server_id), warnings


async def set_tool_enabled(
    session: AsyncSession, principal: Principal, server_id: uuid.UUID, tool_name: str, enabled: bool
) -> McpTool:
    principal.require("admin")
    server = await get_server(session, principal.workspace_id, server_id)
    tool = await session.scalar(
        select(McpTool).where(McpTool.server_id == server.id, McpTool.name == tool_name)
    )
    if tool is None:
        raise NotFoundError(f"Tool '{tool_name}' not found on this server")
    tool.enabled = enabled
    audit_service.record(
        session,
        "mcp.tool_enabled" if enabled else "mcp.tool_disabled",
        principal=principal,
        target_type="mcp_tool",
        target_id=mcp_tool_name(server.slug, tool_name),
    )
    await session.commit()
    return tool


# ---- custom HTTP tools ------------------------------------------------------------------


async def get_custom_tool(
    session: AsyncSession, workspace_id: uuid.UUID, tool_id: uuid.UUID
) -> CustomTool:
    tool = await session.get(CustomTool, tool_id, populate_existing=True)
    if tool is None or tool.workspace_id != workspace_id:
        raise NotFoundError(f"Custom tool {tool_id} not found")
    return tool


async def list_custom_tools(session: AsyncSession, principal: Principal) -> Sequence[CustomTool]:
    stmt = select(CustomTool).where(CustomTool.workspace_id == principal.workspace_id)
    return (await session.scalars(stmt.order_by(CustomTool.slug))).all()


def _validate_custom(settings: Settings, data: CustomToolWrite) -> None:
    hosts = settings.custom_tool_hosts
    if not hosts:
        raise DomainValidationError(
            "Custom HTTP tools are disabled on this server (CUSTOM_TOOL_ALLOWED_HOSTS is empty)"
        )
    from urllib.parse import urlparse

    from app.tools.external import _host_allowed

    parsed = urlparse(data.url_template.replace("{", "x").replace("}", "x"))
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise DomainValidationError("URL must be http(s) with a fixed host")
    if "{" in (urlparse(data.url_template).netloc or ""):
        raise DomainValidationError("The host part of the URL cannot be a parameter")
    if not _host_allowed(parsed.hostname, hosts):
        raise DomainValidationError(
            f"Host '{parsed.hostname}' is not on the allow-list ({', '.join(hosts)})"
        )
    names = [p.name for p in data.params]
    if len(set(names)) != len(names):
        raise DomainValidationError("Parameter names must be unique")
    for p in data.params:
        if p.location == "path" and "{" + p.name + "}" not in data.url_template:
            raise DomainValidationError(f"Path parameter '{p.name}' is not used in the URL")
        if p.location == "body" and data.method == "GET":
            raise DomainValidationError("GET tools cannot have body parameters")


async def save_custom_tool(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    secrets: SecretBox,
    data: CustomToolWrite,
    tool_id: uuid.UUID | None = None,
) -> CustomTool:
    principal.require("admin")
    _validate_custom(settings, data)
    dup = await session.scalar(
        select(CustomTool.id).where(
            CustomTool.workspace_id == principal.workspace_id, CustomTool.slug == data.slug
        )
    )
    if dup is not None and dup != tool_id:
        raise ConflictError(f"A custom tool with slug '{data.slug}' already exists")
    if tool_id is None:
        tool = CustomTool(workspace_id=principal.workspace_id)
        session.add(tool)
    else:
        tool = await get_custom_tool(session, principal.workspace_id, tool_id)
        if tool.slug != data.slug:
            used = await session.scalar(
                select(func.count())
                .select_from(AgentTool)
                .where(AgentTool.tool_name == http_tool_name(tool.slug))
            )
            if used:
                raise ConflictError("Agents use this tool; its slug cannot change")
    tool.slug, tool.description, tool.method = data.slug, data.description, data.method
    tool.url_template, tool.timeout_s, tool.enabled = (
        data.url_template,
        data.timeout_s,
        data.enabled,
    )
    tool.params = [p.model_dump() for p in data.params]
    if data.headers is not None:
        tool.headers_enc = _encrypt_json(secrets, data.headers)
        tool.header_keys = sorted(data.headers)
    await session.flush()
    audit_service.record(
        session,
        "custom_tool.saved",
        principal=principal,
        target_type="custom_tool",
        target_id=tool.id,
        slug=data.slug,
    )
    await session.commit()
    return await get_custom_tool(session, principal.workspace_id, tool.id)


async def delete_custom_tool(
    session: AsyncSession, principal: Principal, tool_id: uuid.UUID
) -> None:
    principal.require("admin")
    tool = await get_custom_tool(session, principal.workspace_id, tool_id)
    used = await session.scalar(
        select(func.count())
        .select_from(AgentTool)
        .where(AgentTool.tool_name == http_tool_name(tool.slug))
    )
    if used:
        raise ConflictError(f"{used} agent(s) use this tool; remove it from them first")
    await session.delete(tool)
    audit_service.record(
        session,
        "custom_tool.deleted",
        principal=principal,
        target_type="custom_tool",
        target_id=tool_id,
    )
    await session.commit()


# ---- bridge to agents and runs ------------------------------------------------------------


async def external_tools(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    settings: Settings,
    secrets: SecretBox,
    names: Sequence[str] | None = None,
    *,
    enabled_only: bool = True,
) -> list[ToolLike]:
    """Runtime tool objects for the workspace's (enabled) external tools.

    With `names` (building a run): only those tools, with secrets decrypted in memory.
    Without (listing/validation): every tool, secrets left encrypted."""
    wanted = set(names) if names is not None else None
    out: list[ToolLike] = []
    rows = await session.execute(
        select(McpServer, McpTool)
        .join(McpTool, McpTool.server_id == McpServer.id)
        .where(McpServer.workspace_id == workspace_id)
    )
    for server, tool in rows.all():
        if enabled_only and not (server.enabled and tool.enabled):
            continue
        name = mcp_tool_name(server.slug, tool.name)
        if wanted is not None and name not in wanted:
            continue
        out.append(
            McpRuntimeTool(
                name=name,
                description=f"[MCP · {server.name}] {tool.description}"[:1024],
                server=server_spec(secrets, server)
                if wanted is not None
                else McpServerSpec(transport=server.transport),  # type: ignore[arg-type]
                remote_name=tool.name,
                input_schema=tool.input_schema or {"type": "object", "properties": {}},
                timeout_s=float(server.timeout_s),
            )
        )
    customs = await session.scalars(
        select(CustomTool).where(CustomTool.workspace_id == workspace_id)
    )
    for c in customs:
        if enabled_only and not c.enabled:
            continue
        name = http_tool_name(c.slug)
        if wanted is not None and name not in wanted:
            continue
        out.append(
            HttpTool(
                name=name,
                description=f"[HTTP] {c.description}"[:1024],
                method=c.method,  # type: ignore[arg-type]
                url_template=c.url_template,
                params=[HttpParam(**p) for p in c.params],
                allowed_hosts=settings.custom_tool_hosts,
                headers=_decrypt_json(secrets, c.headers_enc) if wanted is not None else {},
                timeout_s=float(c.timeout_s),
            )
        )
    return out


async def normalize_external_grant(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    settings: Settings,
    secrets: SecretBox,
    name: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Validate that an agent may be granted this external tool (exists, enabled)."""
    if config:
        raise DomainValidationError(f"Tool '{name}' takes no per-agent configuration")
    available = {t.name for t in await external_tools(session, workspace_id, settings, secrets)}
    if name not in available:
        raise DomainValidationError(f"Unknown or disabled tool: '{name}'")
    return {}
