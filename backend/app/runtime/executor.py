"""Run an agent and stream typed events.

    run = AgentRun(request, provider, tool_registry, caps, tool_ctx)
    async for event in run.stream():
        ...
    run.result  # status, tool_call_count, usage, error, new_messages

The graph runs in a producer task feeding a queue, so the run timeout and cancellation
apply only to agent work, never to the consumer's code. Every stream ends with exactly
one terminal event. If the consumer stops early, the run is cancelled and
`result.status == "cancelled"`.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langgraph.errors import GraphRecursionError

from app.runtime.events import AgentEvent, RunFailureCode, agent_event_adapter
from app.runtime.graph import AGENT_NODE, TOOLS_NODE, build_graph
from app.runtime.limits import effective_limits
from app.runtime.providers.base import Provider, ProviderError
from app.runtime.tool_node import ToolNode
from app.runtime.types import RunRequest, RunResult, RunStatus, RuntimeCaps
from app.skills.prompt import compose_system_prompt
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_DONE = object()
# Token text is emitted in pieces of at most this many characters, so each delta event stays
# well below transport limits (Postgres NOTIFY payloads are capped at 8000 bytes).
MAX_DELTA_CHARS = 1500


class _RunFailure(Exception):
    def __init__(self, status: RunStatus, code: RunFailureCode, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in content
            if not isinstance(b, dict) or b.get("type") in (None, "text")
        )
    return ""


def _pieces(text: str) -> list[str]:
    return [text[i : i + MAX_DELTA_CHARS] for i in range(0, len(text), MAX_DELTA_CHARS)]


class AgentRun:
    def __init__(
        self,
        request: RunRequest,
        provider: Provider,
        tool_registry: ToolRegistry,
        caps: RuntimeCaps,
        tool_ctx: ToolContext,
    ) -> None:
        self.request = request
        self.provider = provider
        self.tool_registry = tool_registry
        self.limits = effective_limits(request.config, caps)
        self.tool_ctx = tool_ctx
        self.result = RunResult()
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._seq = 0
        self._task: asyncio.Task[None] | None = None
        self._started = time.perf_counter()

    # ---- public API -------------------------------------------------------------

    async def stream(self) -> AsyncIterator[AgentEvent]:
        if self._task is not None:
            raise RuntimeError("AgentRun.stream() can only be consumed once")
        self._task = asyncio.create_task(self._produce())
        try:
            while (item := await self._queue.get()) is not _DONE:
                yield item
            await self._task
        finally:
            if not self._task.done():  # consumer stopped early (e.g. client disconnect)
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

    def cancel(self) -> None:
        """Request cancellation; the stream then ends with `run.cancelled`."""
        if self._task is not None and not self._task.done():
            self._task.cancel()

    # ---- internals --------------------------------------------------------------

    def _emit(self, event_type: str, **payload: Any) -> None:
        self._seq += 1
        event = agent_event_adapter.validate_python(
            {"type": event_type, "run_id": self.request.run_id, "seq": self._seq, **payload}
        )
        self._queue.put_nowait(event)

    def _duration_ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)

    def _fail(self, status: RunStatus, code: RunFailureCode, message: str) -> None:
        self.result.status = status
        self.result.error = message
        self._emit("run.failed", code=code, message=message)

    async def _produce(self) -> None:
        cfg = self.request.config
        self._emit(
            "run.started",
            agent_id=cfg.agent_id,
            model=cfg.model,
            conversation_id=self.request.conversation_id,
            user_message_id=self.request.user_message_id,
        )
        try:
            async with asyncio.timeout(self.limits.run_timeout_s):
                await self._execute()
        except _RunFailure as f:
            self._fail(f.status, f.code, f.message)
        except TimeoutError:
            self._fail("timeout", "timeout", f"Run exceeded {self.limits.run_timeout_s:g}s")
        except GraphRecursionError:
            self._fail("limit_exceeded", "limit_exceeded", "Maximum number of steps reached")
        except asyncio.CancelledError:
            self.result.status = "cancelled"
            self._emit("run.cancelled")
        except Exception as e:
            if self.provider.is_provider_error(e):
                logger.warning("Provider error in run %s: %s", self.request.run_id, e)
                self._fail("failed", "provider_error", f"Model provider error: {str(e)[:300]}")
            else:
                logger.exception("Run %s failed", self.request.run_id)
                self._fail("failed", "internal_error", "Internal error while running the agent")
        finally:
            self._queue.put_nowait(_DONE)

    async def _execute(self) -> None:
        cfg = self.request.config
        tool_names = [t.name for t in cfg.tools]

        if tool_names:
            try:
                caps = await self.provider.get_capabilities(cfg.model)
            except ProviderError as e:
                raise _RunFailure("failed", "provider_error", str(e)) from e
            if caps.supports_tools is None:
                raise _RunFailure(
                    "failed",
                    "model_no_tool_support",
                    f"The provider does not report whether model '{cfg.model}' supports tool "
                    "calling. Run the tool-calling check (or mark the model) in Providers, "
                    "or remove the agent's tools.",
                )
            if not caps.supports_tools:
                raise _RunFailure(
                    "failed",
                    "model_no_tool_support",
                    f"Model '{cfg.model}' does not support tool calling. "
                    "Choose a tool-capable model or remove the agent's tools.",
                )

        model: Any = self.provider.create_chat_model(cfg.model, cfg.model_params)
        if tool_names:  # bind ONLY the permitted tools
            model = model.bind_tools(self.tool_registry.function_schemas(tool_names))

        graph = build_graph(
            model,
            compose_system_prompt(cfg.system_prompt, cfg.skills),
            ToolNode(self.tool_registry, cfg.tools, self.limits, self.tool_ctx),
        )

        stop_reason: str | None = None
        async for chunk in graph.astream(
            {"messages": list(self.request.history), "tool_call_count": 0},
            stream_mode=["messages", "custom", "updates"],
            version="v2",
            config={"recursion_limit": self.limits.recursion_limit},
        ):
            kind, data = chunk["type"], chunk["data"]
            if kind == "messages":
                self._on_token(*data)
            elif kind == "custom":
                event_type, payload = data
                self._emit(event_type, **payload)
            elif kind == "updates":
                stop_reason = self._on_update(data) or stop_reason

        if stop_reason == "limit_exceeded":
            raise _RunFailure(
                "limit_exceeded",
                "limit_exceeded",
                f"Tool call limit reached ({self.limits.max_tool_calls})",
            )
        self.result.status = "completed"
        self._emit(
            "run.completed",
            tool_call_count=self.result.tool_call_count,
            usage=self.result.usage,
            duration_ms=self._duration_ms(),
        )

    def _on_token(self, message: BaseMessage, metadata: dict[str, Any]) -> None:
        if metadata.get("langgraph_node") != AGENT_NODE or not isinstance(message, AIMessageChunk):
            return
        reasoning = message.additional_kwargs.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            for piece in _pieces(reasoning):
                self._emit("reasoning.delta", text=piece)
        if text := _text(message.content):
            for piece in _pieces(text):
                self._emit("message.delta", text=piece)

    def _on_update(self, data: dict[str, Any]) -> str | None:
        stop_reason: str | None = None
        for node, update in data.items():
            if not isinstance(update, dict):
                continue
            for msg in update.get("messages", []):
                self.result.new_messages.append(msg)
                if node == AGENT_NODE and isinstance(msg, AIMessage):
                    self._add_usage(msg)
                    if content := _text(msg.content):
                        self._emit("message.completed", message_id=msg.id, content=content)
            if node == TOOLS_NODE:
                self.result.tool_call_count = update.get("tool_call_count", 0)
                stop_reason = update.get("stop_reason")
        return stop_reason

    def _add_usage(self, msg: AIMessage) -> None:
        if not msg.usage_metadata:
            return
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = msg.usage_metadata.get(key)
            if isinstance(value, int):
                self.result.usage[key] = self.result.usage.get(key, 0) + value
