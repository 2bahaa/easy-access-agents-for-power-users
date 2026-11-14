from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["ok", "error"]


class HealthRead(BaseModel):
    status: Literal["ok", "degraded"]
    database: CheckStatus
    ollama: CheckStatus
