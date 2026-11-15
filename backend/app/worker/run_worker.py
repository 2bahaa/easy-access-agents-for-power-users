"""Run worker: claims queued runs from Postgres and executes them.

Runs are independent of HTTP connections: the API only queues a run and follows its events
(services/run_stream.py). A worker can be embedded in the API process (default) or run as
its own process (`python -m app.worker`); any number of workers can share one database.

Event writing is batched: everything the runtime produced since the last write goes into a
single transaction (rows for persisted events + NOTIFY for all events, in order). The
terminal event is written in the same transaction as the run's messages and final status.
"""

import asyncio
import contextlib
import logging
import os
import socket
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Run
from app.observability import current_run_id, tracer
from app.runtime.events import TERMINAL_TYPES, AgentEvent
from app.runtime.executor import AgentRun
from app.services import (
    approval_service,
    knowledge_service,
    run_queue,
    run_service,
    workflow_service,
)
from app.services.provider_service import ProviderResolver
from app.services.pubsub import RUNS_CHANNEL, listen
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class RunWorker:
    def __init__(
        self,
        settings: Settings,
        session_factory: SessionFactory,
        resolver: ProviderResolver,
        tools: ToolRegistry,
        worker_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.resolver = resolver
        self.tools = tools
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._active: dict[uuid.UUID, AgentRun] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._main: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._ingest_wake = asyncio.Event()
        self._ingest: asyncio.Task[None] | None = None
        self.ready = asyncio.Event()  # set once LISTEN is active (tests, startup logs)

    # ---- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        self._main = asyncio.create_task(self._run(), name=f"run-worker-{self.worker_id}")

    async def stop(self, cancel_runs: bool = True) -> None:
        """Stop claiming. With `cancel_runs`, active runs are cancelled (they end as
        'cancelled'); otherwise they are abandoned and later reaped as interrupted."""
        if self._main is not None:
            self._main.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._main
        if cancel_runs:
            for agent_run in list(self._active.values()):
                agent_run.cancel()
        else:
            for task in self._tasks:
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    @property
    def active_run_ids(self) -> list[uuid.UUID]:
        return list(self._active)

    # ---- main loop ----------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            try:
                async with listen(self.settings.listen_dsn, RUNS_CHANNEL) as notifications:
                    self.ready.set()
                    await self._reap()
                    maintenance = asyncio.create_task(self._maintenance())
                    ingest = asyncio.create_task(self._ingest_loop())
                    try:
                        await self._loop(notifications)
                    finally:
                        maintenance.cancel()
                        ingest.cancel()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Run worker loop failed; retrying in 2s")
                self.ready.clear()
                await asyncio.sleep(2)

    async def _loop(self, notifications: "asyncio.Queue[str]") -> None:
        while True:
            await self._fill()
            getter = asyncio.create_task(notifications.get())
            woke = asyncio.create_task(self._wake.wait())
            done, pending = await asyncio.wait(
                {getter, woke},
                timeout=self.settings.run_poll_interval_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            self._wake.clear()
            if getter in done:
                self._on_notification(getter.result())
                while not notifications.empty():
                    self._on_notification(notifications.get_nowait())

    def _on_notification(self, payload: str) -> None:
        if payload == "ingest":
            self._ingest_wake.set()
        elif payload.startswith("cancel:"):
            with contextlib.suppress(ValueError):
                self._cancel_local(uuid.UUID(payload.removeprefix("cancel:")))

    def _cancel_local(self, run_id: uuid.UUID) -> None:
        if (agent_run := self._active.get(run_id)) is not None:
            agent_run.cancel()

    async def _fill(self) -> None:
        """Claim queued runs while there is free capacity."""
        while len(self._tasks) < self.settings.run_worker_concurrency:
            async with self.session_factory() as session:
                run_id = await run_queue.claim_next(session, self.worker_id)
            if run_id is None:
                return
            task = asyncio.create_task(self._execute(run_id), name=f"run-{run_id}")
            self._tasks.add(task)
            task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: "asyncio.Task[None]") -> None:
        self._tasks.discard(task)
        self._wake.set()  # a slot is free: claim more

    async def _ingest_loop(self) -> None:
        """Index queued knowledge documents one at a time (outside the run slots)."""
        while True:
            try:
                while await knowledge_service.process_next_document(
                    self.session_factory, self.resolver, self.settings
                ):
                    pass
            except Exception:
                logger.exception("Knowledge ingestion loop failed")
            self._ingest_wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._ingest_wake.wait(), self.settings.run_poll_interval_s)

    async def _maintenance(self) -> None:
        """Heartbeats for owned runs, missed-cancel recovery and reaping of dead workers."""
        while True:
            await asyncio.sleep(self.settings.run_heartbeat_s)
            try:
                async with self.session_factory() as session:
                    ids = self.active_run_ids
                    await run_queue.heartbeat(session, ids)
                    if ids:
                        flagged = await session.scalars(
                            select(Run.id).where(Run.id.in_(ids), Run.cancel_requested.is_(True))
                        )
                        for run_id in flagged:
                            self._cancel_local(run_id)
                await self._reap()
            except Exception:
                logger.exception("Run worker maintenance failed")

    async def _reap(self) -> None:
        async with self.session_factory() as session:
            if n := await run_queue.reap_stale_runs(session, self.settings.run_stale_after_s):
                logger.warning("Marked %d interrupted run(s) as failed", n)
        async with self.session_factory() as session:
            if n := await approval_service.expire_due(session):
                logger.info("Expired %d approval request(s)", n)

    # ---- executing one run ----------------------------------------------------------

    async def _execute(self, run_id: uuid.UUID) -> None:
        try:
            async with self.session_factory() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    return
                kind = run.kind
                agent_run: Any
                if kind == "workflow":
                    agent_run = await workflow_service.prepare_workflow_run(
                        session,
                        run,
                        settings=self.settings,
                        resolver=self.resolver,
                        tools=self.tools,
                        session_factory=self.session_factory,
                    )
                else:
                    agent_run = await run_service.prepare_agent_run(
                        session,
                        run,
                        settings=self.settings,
                        resolver=self.resolver,
                        tools=self.tools,
                        session_factory=self.session_factory,
                    )
                cancel_requested = run.cancel_requested
        except Exception:
            logger.exception("Could not prepare run %s", run_id)
            await self._fail_unstarted(run_id)
            return

        self._active[run_id] = agent_run
        token = current_run_id.set(str(run_id))
        try:
            with tracer.start_as_current_span(
                f"run.{kind}", attributes={"run.id": str(run_id), "run.kind": kind}
            ):
                if cancel_requested:  # cancelled between queueing and claiming
                    agent_run.cancel()
                await self._drive(run_id, agent_run, kind)
        finally:
            current_run_id.reset(token)
            self._active.pop(run_id, None)

    async def _drive(self, run_id: uuid.UUID, agent_run: Any, kind: str = "agent") -> None:
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()  # None = end of stream

        async def pump() -> None:
            try:
                async for event in agent_run.stream():
                    queue.put_nowait(event)
            finally:
                queue.put_nowait(None)

        producer = asyncio.create_task(pump())
        writable = True
        try:
            while True:
                item = await queue.get()
                batch = [item]
                while not queue.empty():
                    batch.append(queue.get_nowait())
                events = [e for e in batch if e is not None]
                ended = len(events) != len(batch)
                if events and writable:
                    writable = await self._write(run_id, agent_run, events, kind)
                    if not writable:
                        agent_run.cancel()  # run/conversation deleted: stop working
                if ended:
                    break
        finally:
            await producer

    async def _write(
        self, run_id: uuid.UUID, agent_run: Any, events: list[AgentEvent], kind: str = "agent"
    ) -> bool:
        """Write one batch; returns False if the run no longer exists."""
        try:
            async with self.session_factory() as session:
                await run_queue.write_events(session, events)
                if events[-1].type in TERMINAL_TYPES:
                    run = await session.get(Run, run_id)
                    if run is None:
                        return False
                    if kind == "workflow":
                        await workflow_service.apply_result(
                            session, run, agent_run.result, self.settings.approval_ttl_s
                        )
                    else:
                        await run_service.apply_result(
                            session, run, agent_run.result, self.settings.approval_ttl_s
                        )
                await session.commit()
            return True
        except IntegrityError:
            logger.info("Run %s was deleted while running; stopping", run_id)
            return False
        except Exception:
            logger.exception("Failed to write events for run %s", run_id)
            return True  # transient: keep going; the reaper covers a lost terminal write

    async def _fail_unstarted(self, run_id: uuid.UUID) -> None:
        with contextlib.suppress(Exception):
            async with self.session_factory() as session:
                run = await session.get(Run, run_id)
                if run is not None and run.status == "running":
                    await run_queue.fail_run(session, run, "Internal error while starting the run")
                    await session.commit()
