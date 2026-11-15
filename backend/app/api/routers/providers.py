from fastapi import APIRouter, Depends

from app.api.deps import ProviderRegistryDep, get_principal
from app.schemas.providers import ModelRead, ProviderRead
from app.services import provider_service

router = APIRouter(dependencies=[Depends(get_principal)], prefix="/providers", tags=["providers"])


@router.get("")
async def list_providers(registry: ProviderRegistryDep) -> list[ProviderRead]:
    return await provider_service.list_providers(registry)


@router.get("/{provider}/models")
async def list_models(provider: str, registry: ProviderRegistryDep) -> list[ModelRead]:
    return await provider_service.list_models(registry, provider)
