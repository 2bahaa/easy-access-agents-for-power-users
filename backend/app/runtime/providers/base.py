"""Provider seam: each provider lists models, reports capabilities and builds a LangChain
chat model. Adding a provider = implementing this protocol + registering it."""

from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel


class ProviderError(Exception):
    """Provider unreachable or returned an unexpected response. Message is user-safe."""


class ModelNotFoundError(ProviderError):
    pass


@dataclass(frozen=True)
class ModelCapabilities:
    """Capabilities as reported by the provider. None = the provider does not say; it is
    never guessed from the model name (see services/provider_service.py for overrides and
    the live tool-calling probe)."""

    supports_tools: bool | None
    supports_thinking: bool | None


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size: int | None
    supports_tools: bool | None
    supports_thinking: bool | None
    context_window: int | None = None
    display_name: str | None = None


class Provider(Protocol):
    name: str

    async def is_available(self) -> bool: ...

    async def list_models(self) -> list[ModelInfo]: ...

    async def get_capabilities(self, model: str) -> ModelCapabilities: ...

    def create_chat_model(self, model: str, params: dict[str, Any]) -> BaseChatModel: ...

    def is_provider_error(self, exc: BaseException) -> bool:
        """True if an exception raised by the chat model is a provider/transport failure."""
        ...
