from fastapi import APIRouter

from app.api.deps import PrincipalDep, ProviderResolverDep, SessionDep, SettingsDep, ToolRegistryDep
from app.schemas.tools import ToolInfo
from app.services import capability_service
from app.tools.base import ToolLike

router = APIRouter(prefix="/tools", tags=["tools"])


def _info(t: ToolLike, source: str, default_timeout: float) -> ToolInfo:
    return ToolInfo(
        name=t.name,
        description=t.description,
        args_schema=t.args_schema(),
        config_schema=t.config_schema(),
        timeout_s=t.timeout_s or default_timeout,
        source=source,
    )


@router.get("")
async def list_tools(
    principal: PrincipalDep,
    session: SessionDep,
    registry: ToolRegistryDep,
    settings: SettingsDep,
    resolver: ProviderResolverDep,
) -> list[ToolInfo]:
    """Native tools plus this workspace's enabled MCP and custom HTTP tools."""
    external = await capability_service.external_tools(
        session, principal.workspace_id, settings, resolver.secrets
    )
    return [_info(t, "native", settings.tool_timeout_s) for t in registry.all()] + [
        _info(t, "mcp" if t.name.startswith("mcp__") else "http", settings.tool_timeout_s)
        for t in sorted(external, key=lambda x: x.name)
    ]
