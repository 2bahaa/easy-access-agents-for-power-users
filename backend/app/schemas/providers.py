from pydantic import BaseModel


class ProviderRead(BaseModel):
    name: str
    available: bool


class ModelRead(BaseModel):
    name: str
    size: int | None
    supports_tools: bool
    supports_thinking: bool
