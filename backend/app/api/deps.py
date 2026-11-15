from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.runtime.providers.registry import ProviderRegistry
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
