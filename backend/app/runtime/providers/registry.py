import httpx

from app.runtime.providers.base import Provider
from app.runtime.providers.cloud import ProviderSpec, build_cloud_provider
from app.runtime.providers.ollama import OllamaProvider


class UnknownProviderError(KeyError):
    pass


class ProviderRegistry:
    def __init__(self, providers: list[Provider]) -> None:
        self._providers = {p.name: p for p in providers}

    def get(self, name: str) -> Provider:
        try:
            return self._providers[name]
        except KeyError:
            raise UnknownProviderError(name) from None

    def __contains__(self, name: object) -> bool:
        return name in self._providers

    def all(self) -> list[Provider]:
        return list(self._providers.values())


def build_default_providers(ollama_base_url: str) -> ProviderRegistry:
    return ProviderRegistry([OllamaProvider(ollama_base_url)])


def build_provider(
    spec: ProviderSpec, name: str, transport: httpx.AsyncBaseTransport | None = None
) -> Provider:
    """Build a provider for a stored connection (any kind, including remote Ollama)."""
    if spec.kind == "ollama":
        if not spec.base_url:
            raise ValueError("An Ollama connection needs a base URL")
        return OllamaProvider(spec.base_url, name=name, transport=transport)
    return build_cloud_provider(spec, name, transport=transport)
