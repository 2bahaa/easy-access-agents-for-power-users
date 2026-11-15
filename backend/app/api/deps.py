from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.runtime.providers.registry import ProviderRegistry
from app.services.auth_service import resolve_principal
from app.services.principal import Principal
from app.services.run_service import SessionFactory
from app.tools.registry import ToolRegistry


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with maker() as session:
        yield session


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_tool_registry(request: Request) -> ToolRegistry:
    registry: ToolRegistry = request.app.state.tool_registry
    return registry


def get_provider_registry(request: Request) -> ProviderRegistry:
    registry: ProviderRegistry = request.app.state.provider_registry
    return registry


def get_session_factory(request: Request) -> SessionFactory:
    """For work that outlives the request handler (streaming responses)."""
    factory: SessionFactory = request.app.state.sessionmaker
    return factory


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
ToolRegistryDep = Annotated[ToolRegistry, Depends(get_tool_registry)]
ProviderRegistryDep = Annotated[ProviderRegistry, Depends(get_provider_registry)]
SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def get_principal(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
    x_workspace_id: Annotated[str | None, Header()] = None,
) -> Principal:
    """Every protected endpoint depends on this: 401 without valid credentials, 403 for a
    workspace the caller is not a member of. Authorization is re-checked in services."""
    return await resolve_principal(session, settings, _bearer(authorization), x_workspace_id)


PrincipalDep = Annotated[Principal, Depends(get_principal)]
