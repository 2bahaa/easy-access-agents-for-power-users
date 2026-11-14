from typing import Any

from pydantic import BaseModel


class ToolInfo(BaseModel):
    name: str
    description: str
    args_schema: dict[str, Any]
    config_schema: dict[str, Any]
    timeout_s: float
