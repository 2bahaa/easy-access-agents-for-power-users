"""Test fixtures.

A dedicated test database (`<dev db>_test`, or TEST_DATABASE_URL) is recreated once
per session and migrated with Alembic, so every test run also exercises the
migrations. Data is really committed (runs execute in a worker on other connections and
use LISTEN/NOTIFY, which only see committed data); every DB test starts from empty tables.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

import pytest
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.config import BACKEND_DIR, Settings, get_settings
from app.db.models import Base, Organization, Workspace
from app.main import create_app
from app.runtime.providers.registry import ProviderRegistry
from app.services.principal import Principal
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
        skills_dir=tmp_path_factory.mktemp("skills"),  # no built-in skills seeded in tests
        run_heartbeat_s=0.2,
        run_poll_interval_s=0.2,
        run_stale_after_s=2.0,
        jwt_secret="test-secret-not-for-production-0123456789",
    )


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def clean_db(engine: AsyncEngine) -> None:
    """Start from empty tables (TRUNCATE is fast and resets everything in one statement)."""
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def session(engine: AsyncEngine, clean_db: None) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(bind=engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture
async def workspace(session: AsyncSession) -> Workspace:
    """An organization + workspace created directly in the DB (for service-level tests)."""
    org = Organization(name="Test org")
    session.add(org)
    await session.flush()
    ws = Workspace(org_id=org.id, name="Test", slug=f"test-{uuid.uuid4().hex[:6]}")
    session.add(ws)
    await session.commit()
    return ws


async def principal_of(client: AsyncClient) -> Principal:
    """The Principal behind an authenticated test client (for calling services directly)."""
    me = (await client.get("/api/auth/me")).json()
    org = next(
        o
        for o in me["organizations"]
        if any(w["id"] == me["current_workspace_id"] for w in o["workspaces"])
    )
    return Principal(
        user_id=uuid.UUID(me["user"]["id"]),
        org_id=uuid.UUID(org["id"]),
        workspace_id=uuid.UUID(me["current_workspace_id"]),
        role=me["role"],
    )


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider(no_tool_models={"plain:1b"})


@pytest.fixture
async def app(
    settings: Settings, clean_db: None, fake_provider: FakeProvider
) -> AsyncIterator[FastAPI]:
    """The real app (lifespan included: engine, embedded run worker) on the test database,
    with the fake provider."""
    application = create_app(settings, provider_registry=ProviderRegistry([fake_provider]))
    async with application.router.lifespan_context(application):
        await asyncio.wait_for(application.state.run_worker.ready.wait(), timeout=10)
        yield application


async def register_user(
    client: AsyncClient, email: str, password: str = "correct horse battery", name: str = ""
) -> str:
    """Register via the API and return an access token."""
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": password, "name": name or email}
    )
    assert resp.status_code == 201, resp.text
    token: str = resp.json()["access_token"]
    return token


UserClientFactory = Callable[[str], Awaitable[AsyncClient]]


@pytest.fixture
async def make_client(app: FastAPI) -> AsyncIterator[UserClientFactory]:
    """Factory: a new registered user (own organization/workspace) with an authenticated client."""
    clients: list[AsyncClient] = []

    async def _make(email: str) -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        token = await register_user(c, email)
        c.headers["Authorization"] = f"Bearer {token}"
        return c

    yield _make
    for c in clients:
        await c.aclose()


@pytest.fixture
async def client(make_client: UserClientFactory) -> AsyncClient:
    """Authenticated client of the first registered user (owner of its organization)."""
    return await make_client("owner@example.com")


@pytest.fixture
async def anon_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
