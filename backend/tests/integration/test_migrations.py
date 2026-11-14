"""Alembic round trip on a throwaway database: empty -> head -> base -> head."""

import asyncio

from sqlalchemy import inspect, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.db.models import Base
from tests.conftest import alembic_config, recreate_database


async def _tables(url: str) -> set[str]:
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    await engine.dispose()
    return names - {"alembic_version"}


def test_upgrade_downgrade_roundtrip(database_url: str) -> None:
    url = make_url(database_url)
    url_str = url.set(database=f"{url.database}_migrations").render_as_string(hide_password=False)
    asyncio.run(recreate_database(url_str))
    cfg = alembic_config(url_str)

    command.upgrade(cfg, "head")
    assert asyncio.run(_tables(url_str)) == set(Base.metadata.tables)

    command.downgrade(cfg, "base")
    assert asyncio.run(_tables(url_str)) == set()

    command.upgrade(cfg, "head")
    assert asyncio.run(_tables(url_str)) == set(Base.metadata.tables)
