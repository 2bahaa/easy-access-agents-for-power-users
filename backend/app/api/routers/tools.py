from fastapi import APIRouter

from app.api.deps import SettingsDep, ToolRegistryDep
from app.schemas.tools import ToolInfo

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def list_tools(registry: ToolRegistryDep, settings: SettingsDep) -> list[ToolInfo]:
    return [
        ToolInfo(
            name=t.name,
            description=t.description,
            args_schema=t.args_schema(),
            config_schema=t.config_schema(),
            timeout_s=t.timeout_s or settings.tool_timeout_s,
        )
        for t in registry.all()
    ]
