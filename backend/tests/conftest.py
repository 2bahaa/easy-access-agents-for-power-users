"""Test fixtures.

A dedicated test database (`<dev db>_test`, or TEST_DATABASE_URL) is recreated once
per session and migrated with Alembic, so every test run also exercises the
migrations. Each test runs inside a transaction that is rolled back afterwards.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.api.deps import get_session
from app.config import BACKEND_DIR, Settings, get_settings
from app.main import create_app
from app.runtime.providers.registry import ProviderRegistry
from tests.fakes import FakeProvider


def _test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


async def recreate_database(url: str) -> None:
    parsed = make_url(url)
    admin = create_async_engine(
        parsed.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{parsed.database}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    await admin.dispose()


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = _test_database_url()
    asyncio.run(recreate_database(url))
    command.upgrade(alembic_config(url), "head")
    yield url


@pytest.fixture(scope="session")
def settings(database_url: str, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return Settings(
        database_url=database_url,
        workspace_dir=tmp_path_factory.mktemp("workspace"),
        skills_dir=Path(BACKEND_DIR / "skills"),
    )


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        trans = await conn.begin()
        s = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield s
        finally:
            await s.close()
            await trans.rollback()


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider(no_tool_models={"plain:1b"})


@pytest.fixture
async def client(
    settings: Settings, session: AsyncSession, fake_provider: FakeProvider
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, provider_registry=ProviderRegistry([fake_provider]))

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
