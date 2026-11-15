"""MCP servers and custom HTTP tools (admin-managed)."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import PrincipalDep, ProviderResolverDep, SessionDep, SettingsDep
from app.db.models import CustomTool, McpServer
from app.schemas.capabilities import (
    CustomToolRead,
    CustomToolWrite,
    McpServerCreate,
    McpServerRead,
    McpServerUpdate,
    McpToolRead,
    RefreshResult,
    ToolToggle,
)
from app.services import capability_service
from app.tools.external import http_tool_name

router = APIRouter(tags=["tools"])


async def _server_read(session: SessionDep, server: McpServer) -> McpServerRead:
    tools = await capability_service.server_tools(session, server.id)
    return McpServerRead(
        id=server.id,
        name=server.name,
        slug=server.slug,
        transport=server.transport,
        command=server.command,
        args=[str(a) for a in server.args],
        url=server.url,
        secret_keys=[str(k) for k in server.secret_keys],
        enabled=server.enabled,
        timeout_s=server.timeout_s,
        status=server.status,
        last_error=server.last_error,
        last_checked_at=server.last_checked_at,
        tools=[McpToolRead.model_validate(t) for t in tools],
    )


def _custom_read(tool: CustomTool) -> CustomToolRead:
    return CustomToolRead.model_validate(
        {
            **{
                c: getattr(tool, c)
                for c in (
                    "id",
                    "slug",
                    "description",
                    "method",
                    "url_template",
                    "params",
                    "header_keys",
                    "timeout_s",
                    "enabled",
                    "updated_at",
                )
            },
            "tool_name": http_tool_name(tool.slug),
        }
    )


@router.get("/mcp-servers")
async def list_servers(principal: PrincipalDep, session: SessionDep) -> list[McpServerRead]:
    return [
        await _server_read(session, s)
        for s in await capability_service.list_servers(session, principal)
    ]


@router.post("/mcp-servers", status_code=status.HTTP_201_CREATED)
async def create_server(
    data: McpServerCreate,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    resolver: ProviderResolverDep,
) -> McpServerRead:
    server = await capability_service.create_server(
        session, principal, settings, resolver.secrets, data
    )
    return await _server_read(session, server)


@router.patch("/mcp-servers/{server_id}")
async def update_server(
    server_id: uuid.UUID,
    data: McpServerUpdate,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    resolver: ProviderResolverDep,
) -> McpServerRead:
    server = await capability_service.update_server(
        session, principal, settings, resolver.secrets, server_id, data
    )
    return await _server_read(session, server)


@router.delete("/mcp-servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await capability_service.delete_server(session, principal, server_id)


@router.post("/mcp-servers/{server_id}/refresh")
async def refresh_server(
    server_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    resolver: ProviderResolverDep,
) -> RefreshResult:
    """Connect, discover tools (new ones are added disabled) and record health."""
    server, warnings = await capability_service.refresh_server(
        session, principal, resolver.secrets, server_id
    )
    return RefreshResult(server=await _server_read(session, server), warnings=warnings)


@router.put("/mcp-servers/{server_id}/tools/{tool_name}")
async def toggle_tool(
    server_id: uuid.UUID,
    tool_name: str,
    data: ToolToggle,
    principal: PrincipalDep,
    session: SessionDep,
) -> McpToolRead:
    tool = await capability_service.set_tool_enabled(
        session, principal, server_id, tool_name, data.enabled
    )
    return McpToolRead.model_validate(tool)


@router.get("/custom-tools")
async def list_custom(principal: PrincipalDep, session: SessionDep) -> list[CustomToolRead]:
    return [_custom_read(t) for t in await capability_service.list_custom_tools(session, principal)]


@router.post("/custom-tools", status_code=status.HTTP_201_CREATED)
async def create_custom(
    data: CustomToolWrite,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    resolver: ProviderResolverDep,
) -> CustomToolRead:
    return _custom_read(
        await capability_service.save_custom_tool(
            session, principal, settings, resolver.secrets, data
        )
    )


@router.put("/custom-tools/{tool_id}")
async def update_custom(
    tool_id: uuid.UUID,
    data: CustomToolWrite,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    resolver: ProviderResolverDep,
) -> CustomToolRead:
    tool = await capability_service.save_custom_tool(
        session, principal, settings, resolver.secrets, data, tool_id
    )
    return _custom_read(tool)


@router.delete("/custom-tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom(tool_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await capability_service.delete_custom_tool(session, principal, tool_id)
