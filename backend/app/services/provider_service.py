"""Provider/model discovery use cases."""

import asyncio

from app.runtime.providers.base import Provider, ProviderError
from app.runtime.providers.registry import ProviderRegistry, UnknownProviderError
from app.schemas.providers import ModelRead, ProviderRead
from app.services.errors import NotFoundError, ProviderUnavailableError


def get_provider(registry: ProviderRegistry, name: str) -> Provider:
    try:
        return registry.get(name)
    except UnknownProviderError:
        raise NotFoundError(f"Provider '{name}' not found") from None


async def list_providers(registry: ProviderRegistry) -> list[ProviderRead]:
    providers = registry.all()
    available = await asyncio.gather(*(p.is_available() for p in providers))
    return [
        ProviderRead(name=p.name, available=a) for p, a in zip(providers, available, strict=True)
    ]


async def list_models(registry: ProviderRegistry, name: str) -> list[ModelRead]:
    provider = get_provider(registry, name)
    try:
        models = await provider.list_models()
    except ProviderError as e:
        raise ProviderUnavailableError(str(e)) from e
    return [
        ModelRead(
            name=m.name,
            size=m.size,
            supports_tools=m.supports_tools,
            supports_thinking=m.supports_thinking,
        )
        for m in models
    ]
