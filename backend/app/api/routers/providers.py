import uuid

from fastapi import APIRouter, status

from app.api.deps import PrincipalDep, ProviderResolverDep, SessionDep, SettingsDep
from app.schemas.providers import (
    CapabilityOverride,
    ModelRead,
    ProbeResult,
    ProviderConnectionCreate,
    ProviderConnectionUpdate,
    ProviderRead,
)
from app.services import provider_service

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
async def list_providers(
    principal: PrincipalDep, session: SessionDep, resolver: ProviderResolverDep
) -> list[ProviderRead]:
    """Built-in providers (e.g. "ollama") plus this workspace's connections. Secrets are never
    returned: only `has_secret` and a short `secret_hint`."""
    return await provider_service.list_providers(session, principal, resolver)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_provider(
    data: ProviderConnectionCreate,
    principal: PrincipalDep,
    session: SessionDep,
    resolver: ProviderResolverDep,
    settings: SettingsDep,
) -> ProviderRead:
    conn = await provider_service.create_connection(session, principal, resolver, settings, data)
    return provider_service._to_read(conn)


@router.patch("/{connection_id}")
async def update_provider(
    connection_id: uuid.UUID,
    data: ProviderConnectionUpdate,
    principal: PrincipalDep,
    session: SessionDep,
    resolver: ProviderResolverDep,
    settings: SettingsDep,
) -> ProviderRead:
    conn = await provider_service.update_connection(
        session, principal, resolver, settings, connection_id, data
    )
    return provider_service._to_read(conn)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    connection_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    await provider_service.delete_connection(session, principal, connection_id)


@router.post("/{provider}/test")
async def test_provider(
    provider: str, principal: PrincipalDep, session: SessionDep, resolver: ProviderResolverDep
) -> ProviderRead:
    """Health check (lists models) and records the result."""
    return await provider_service.test_connection(session, principal, resolver, provider)


@router.get("/{provider}/models")
async def list_models(
    provider: str, principal: PrincipalDep, session: SessionDep, resolver: ProviderResolverDep
) -> list[ModelRead]:
    return await provider_service.list_models(session, principal, resolver, provider)


@router.put("/{provider}/models/{model:path}/capabilities", status_code=status.HTTP_204_NO_CONTENT)
async def set_capabilities(
    provider: str,
    model: str,
    data: CapabilityOverride,
    principal: PrincipalDep,
    session: SessionDep,
    resolver: ProviderResolverDep,
) -> None:
    """Declare (or clear) tool support for a model whose provider does not report it."""
    await provider_service.set_override(
        session, principal, resolver, provider, model, data.supports_tools
    )


@router.post("/{provider}/models/{model:path}/probe")
async def probe_model(
    provider: str,
    model: str,
    principal: PrincipalDep,
    session: SessionDep,
    resolver: ProviderResolverDep,
) -> ProbeResult:
    """Live tool-calling check: one small request asking the model to call a test tool."""
    return await provider_service.probe_tool_support(session, principal, resolver, provider, model)
