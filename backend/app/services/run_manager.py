"""Owns in-flight runs (single process).

Each run is driven by a background task that persists events and the final result,
independent of any HTTP connection. Subscribers (the SSE response) read events from a
queue. Cancelling — via the cancel endpoint or a client disconnect — is a synchronous
`cancel(run_id)`, so it is safe to call from a cancelled request context.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

from app.runtime.events import AgentEvent
from app.runtime.executor import AgentRun
from app.runtime.types import RunResult

logger = logging.getLogger(__name__)


class RunRecorder(Protocol):
    async def record_event(self, event: AgentEvent) -> None: ...

    async def finish(self, result: RunResult) -> None: ...


@dataclass
class ActiveRun:
    run_id: uuid.UUID
    conversation_id: uuid.UUID
    agent_run: AgentRun
    queue: asyncio.Queue[AgentEvent | None] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[None] | None = None

    async def events(self) -> AsyncIterator[AgentEvent]:
        while (event := await self.queue.get()) is not None:
            yield event


class RunManager:
    def __init__(self) -> None:
        self._active: dict[uuid.UUID, ActiveRun] = {}

    def is_active(self, run_id: uuid.UUID) -> bool:
        return run_id in self._active

    def active_run_id(self, conversation_id: uuid.UUID) -> uuid.UUID | None:
        return next(
            (r.run_id for r in self._active.values() if r.conversation_id == conversation_id),
            None,
        )

    def has_active_run(self, conversation_id: uuid.UUID) -> bool:
        return self.active_run_id(conversation_id) is not None

    def start(
        self,
        run_id: uuid.UUID,
        conversation_id: uuid.UUID,
        agent_run: AgentRun,
        recorder: RunRecorder,
    ) -> ActiveRun:
        active = ActiveRun(run_id=run_id, conversation_id=conversation_id, agent_run=agent_run)
        self._active[run_id] = active
        active.task = asyncio.create_task(self._drive(active, recorder), name=f"run-{run_id}")
        return active

    def cancel(self, run_id: uuid.UUID) -> bool:
        active = self._active.get(run_id)
        if active is None:
            return False
        active.agent_run.cancel()
        return True

    async def shutdown(self) -> None:
        """Cancel and await all runs (app shutdown)."""
        tasks = [r.task for r in self._active.values() if r.task is not None]
        for run_id in list(self._active):
            self.cancel(run_id)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _drive(self, active: ActiveRun, recorder: RunRecorder) -> None:
        try:
            async for event in active.agent_run.stream():
                if event.persisted:
                    try:
                        await recorder.record_event(event)
                    except Exception:
                        logger.exception(
                            "Failed to persist event %s of run %s", event.seq, active.run_id
                        )
                active.queue.put_nowait(event)
        finally:
            try:
                await recorder.finish(active.agent_run.result)
            except Exception:
                logger.exception("Failed to persist result of run %s", active.run_id)
            self._active.pop(active.run_id, None)
            active.queue.put_nowait(None)  # end of stream, after persistence
