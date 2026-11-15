"""Durable execution: runs live in Postgres, not in a request or a process.

Covers the queue, worker independence, resume/replay, cross-process fan-out, reaping,
exclusive claiming and the one-active-run-per-conversation guarantee.
"""

import asyncio
import contextlib
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.crypto import SecretBox
from app.db.models import Run
from app.main import create_app
from app.runtime.providers.registry import ProviderRegistry
from app.services import run_queue, run_service
from app.services.provider_service import ProviderResolver
from app.services.run_stream import follow_run
from app.tools.registry import build_default_registry
from app.worker.run_worker import RunWorker
from tests.conftest import principal_of, register_user
from tests.fakes import FakeProvider, reply
from tests.integration.test_runs_api import active_run, wait_for_status
from tests.sse_helpers import create_agent, create_conversation, parse_sse

PASSWORD = "correct horse battery"


def types(events: list[dict[str, Any]]) -> list[str]:
    return [e["event"] for e in events]


@contextlib.asynccontextmanager
async def api_without_worker(settings: Settings, provider: FakeProvider):  # type: ignore[no-untyped-def]
    """An API process that only queues runs (RUN_WORKER_EMBEDDED=false)."""
    api = create_app(
        settings.model_copy(update={"run_worker_embedded": False}),
        provider_registry=ProviderRegistry([provider]),
    )
    async with api.router.lifespan_context(api):
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as c:
            # Sign in (first call registers; a "restarted" API reuses the same account).
            resp = await c.post(
                "/api/auth/login", json={"email": "api@example.com", "password": PASSWORD}
            )
            token = (
                resp.json()["access_token"]
                if resp.status_code == 200
                else await register_user(c, "api@example.com", PASSWORD)
            )
            c.headers["Authorization"] = f"Bearer {token}"
            yield api, c


@contextlib.asynccontextmanager
async def standalone_worker(app: FastAPI, provider: FakeProvider, worker_id: str):  # type: ignore[no-untyped-def]
    worker = RunWorker(
        app.state.settings,
        app.state.sessionmaker,
        ProviderResolver(ProviderRegistry([provider]), SecretBox("")),
        build_default_registry(),
        worker_id=worker_id,
    )
    worker.start()
    await asyncio.wait_for(worker.ready.wait(), timeout=10)
    try:
        yield worker
    finally:
        await worker.stop(cancel_runs=True)


async def test_disconnect_does_not_cancel_and_stream_replays(
    client: AsyncClient, app: FastAPI, fake_provider: FakeProvider
) -> None:
    fake_provider.model.delay_s = 0.3
    fake_provider.model.responses = [reply("Still finished.")]
    agent = await create_agent(client, tools=[])
    conv = await create_conversation(client, agent["id"])

    async with app.state.sessionmaker() as session:
        run = await run_service.start_run(
            session,
            await principal_of(client),
            uuid.UUID(conv["id"]),
            "go",
            resolver=app.state.provider_resolver,
        )
    # A follower reads the first event and goes away (client disconnect).
    follower = follow_run(app.state.sessionmaker, app.state.settings.listen_dsn, run.id)
    first = await asyncio.wait_for(anext(follower), timeout=5)
    assert first.type == "run.started"
    await follower.aclose()

    finished = await wait_for_status(client, run.id, "completed")
    assert finished["finished_at"] is not None

    # Reattach after the fact: the full persisted timeline is replayed and the stream ends.
    replay = parse_sse((await client.get(f"/api/runs/{run.id}/stream")).text)
    assert types(replay) == ["run.started", "message.completed", "run.completed"]

    # Resume after seq 1 (Last-Event-ID): only later persisted events.
    resumed = parse_sse(
        (await client.get(f"/api/runs/{run.id}/stream", headers={"Last-Event-ID": "1"})).text
    )
    assert types(resumed) == ["message.completed", "run.completed"]
    assert all(int(e["id"]) > 1 for e in resumed)
    via_query = parse_sse((await client.get(f"/api/runs/{run.id}/stream?after=1")).text)
    assert types(via_query) == types(resumed)


async def test_second_follower_gets_live_events(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    fake_provider.model.delay_s = 0.5
    fake_provider.model.responses = [reply("Live for everyone.")]
    agent = await create_agent(client, tools=[])
    conv = await create_conversation(client, agent["id"])
    first = asyncio.create_task(
        client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "hi"})
    )
    run_id = await active_run(client, conv["id"])
    second = await client.get(f"/api/runs/{run_id}/stream")

    events_a = parse_sse((await asyncio.wait_for(first, timeout=5)).text)
    events_b = parse_sse(second.text)
    assert events_a[-1]["event"] == events_b[-1]["event"] == "run.completed"
    # The live follower also receives token deltas (not persisted, only published).
    assert "message.delta" in types(events_b)
    text_b = "".join(e["data"]["text"] for e in events_b if e["event"] == "message.delta")
    assert text_b == "Live for everyone."


async def test_stream_unknown_run_404(client: AsyncClient) -> None:
    assert (await client.get(f"/api/runs/{uuid.uuid4()}/stream")).status_code == 404


async def test_runs_wait_queued_until_a_worker_runs_them(
    settings: Settings, clean_db: None, fake_provider: FakeProvider
) -> None:
    """The API only queues; a separate worker executes. The API instance can be replaced
    while the run is in flight (API restart) and a new instance sees the result."""
    fake_provider.model.responses = [reply("Done by the worker.")]
    async with api_without_worker(settings, fake_provider) as (api, c):
        agent = await create_agent(c, tools=[])
        conv = await create_conversation(c, agent["id"])
        resp_task = asyncio.create_task(
            c.post(f"/api/conversations/{conv['id']}/messages", json={"content": "work"})
        )
        await asyncio.sleep(0.5)
        runs = (await c.get(f"/api/conversations/{conv['id']}")).json()["runs"]
        assert [r["status"] for r in runs] == ["queued"]  # nobody executes it yet

        async with standalone_worker(api, fake_provider, "w-1"):
            events = parse_sse((await asyncio.wait_for(resp_task, timeout=10)).text)
            assert events[-1]["event"] == "run.completed"

    # A fresh API instance (the "restarted" API) reads the finished run.
    async with api_without_worker(settings, fake_provider) as (_api2, c2):
        detail = (await c2.get(f"/api/conversations/{conv['id']}")).json()
        assert detail["runs"][0]["status"] == "completed"
        assert detail["messages"][-1]["content"] == "Done by the worker."


async def test_cancel_queued_run_without_worker(
    settings: Settings, clean_db: None, fake_provider: FakeProvider
) -> None:
    async with api_without_worker(settings, fake_provider) as (api, c):
        agent = await create_agent(c, tools=[])
        conv = await create_conversation(c, agent["id"])
        async with api.state.sessionmaker() as session:
            run = await run_service.start_run(
                session,
                await principal_of(c),
                uuid.UUID(conv["id"]),
                "x",
                resolver=api.state.provider_resolver,
            )
        assert (await c.post(f"/api/runs/{run.id}/cancel")).status_code == 202
        detail = (await c.get(f"/api/runs/{run.id}")).json()
        assert detail["status"] == "cancelled" and detail["finished_at"] is not None
        events = parse_sse((await c.get(f"/api/runs/{run.id}/stream")).text)
        assert types(events) == ["run.cancelled"]
        # The conversation is free again for a new run.
        async with api.state.sessionmaker() as session:
            assert await run_service.active_run_id(session, uuid.UUID(conv["id"])) is None


async def test_dead_worker_runs_are_reaped_and_followers_see_the_end(
    client: AsyncClient, app: FastAPI, fake_provider: FakeProvider
) -> None:
    agent = await create_agent(client, tools=[])
    conv = await create_conversation(client, agent["id"])
    sm: async_sessionmaker[AsyncSession] = app.state.sessionmaker
    # Simulate a run claimed by a worker that then died (no heartbeats).
    async with sm() as session:
        run = Run(
            workspace_id=(await principal_of(client)).workspace_id,
            conversation_id=uuid.UUID(conv["id"]),
            agent_id=uuid.UUID(agent["id"]),
            status="running",
            worker_id="dead-worker",
        )
        session.add(run)
        await session.commit()
        await session.execute(update(Run).where(Run.id == run.id).values(heartbeat_at=None))
        await session.commit()

    stream = await asyncio.wait_for(client.get(f"/api/runs/{run.id}/stream"), timeout=10)
    events = parse_sse(stream.text)
    assert types(events) == ["run.failed"]
    assert events[0]["data"]["message"] == run_queue.INTERRUPTED_ERROR
    assert (await client.get(f"/api/runs/{run.id}")).json()["status"] == "failed"


async def test_live_worker_heartbeats_keep_long_runs_alive(
    client: AsyncClient, fake_provider: FakeProvider, settings: Settings
) -> None:
    # Longer than run_stale_after_s (2s in tests): heartbeats must prevent reaping.
    fake_provider.model.delay_s = settings.run_stale_after_s + 1.0
    fake_provider.model.responses = [reply("Slow but alive.")]
    agent = await create_agent(client, tools=[])
    conv = await create_conversation(client, agent["id"])
    resp = await asyncio.wait_for(
        client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "slow"}),
        timeout=15,
    )
    assert parse_sse(resp.text)[-1]["event"] == "run.completed"


async def test_two_workers_never_execute_a_run_twice(settings: Settings, clean_db: None) -> None:
    provider = FakeProvider()
    provider.model.delay_s = 0.1
    provider.model.responses = [reply(f"answer {i}") for i in range(6)]
    async with api_without_worker(settings, provider) as (api, c):
        agent = await create_agent(c, tools=[])
        convs = [await create_conversation(c, agent["id"]) for _ in range(6)]
        run_ids = []
        async with api.state.sessionmaker() as session:
            for conv in convs:
                run = await run_service.start_run(
                    session,
                    await principal_of(c),
                    uuid.UUID(conv["id"]),
                    "q",
                    resolver=api.state.provider_resolver,
                )
                run_ids.append(run.id)
        async with (
            standalone_worker(api, provider, "w-a") as wa,
            standalone_worker(api, provider, "w-b") as wb,
        ):
            assert wa.worker_id != wb.worker_id
            finished = [await wait_for_status(c, rid, "completed", within_s=15) for rid in run_ids]
        assert len(provider.model.prompts) == 6  # each run executed exactly once
        assert {r["status"] for r in finished} == {"completed"}


async def test_large_events_are_delivered_by_reference(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    big = "x" * 20_000  # larger than the 8 kB NOTIFY payload limit
    fake_provider.model.responses = [reply(big)]
    agent = await create_agent(client, tools=[])
    conv = await create_conversation(client, agent["id"])
    resp = await client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "big"})
    events = parse_sse(resp.text)
    completed = next(e for e in events if e["event"] == "message.completed")
    assert completed["data"]["content"] == big


async def test_database_allows_one_active_run_per_conversation(
    settings: Settings, clean_db: None, fake_provider: FakeProvider
) -> None:
    # No worker: nothing claims, finishes or reaps these rows during the test.
    async with api_without_worker(settings, fake_provider) as (api, c):
        agent = await create_agent(c, tools=[])
        conv = await create_conversation(c, agent["id"])
        ids = {
            "workspace_id": (await principal_of(c)).workspace_id,
            "conversation_id": uuid.UUID(conv["id"]),
            "agent_id": uuid.UUID(agent["id"]),
        }
        sm: async_sessionmaker[AsyncSession] = api.state.sessionmaker
        async with sm() as session:
            session.add(Run(**ids, status="running", worker_id="x"))
            await session.commit()
            session.add(Run(**ids, status="queued"))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
            # Finished runs do not count as active.
            session.add(Run(**ids, status="completed"))
            await session.commit()
