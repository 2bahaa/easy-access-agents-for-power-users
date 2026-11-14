"""Tool execution node: limit -> started -> permission -> validation -> timeout-bound run -> event.

Every failure is returned to the model as an error ToolMessage (so it can recover) and
emitted as `tool.call.failed`; nothing here crashes the run.
"""

import asyncio
import logging
import time
import uuid
from typing import Any

from langchain_core.messages import AIMessage, ToolCall, ToolMessage
from langgraph.config import get_stream_writer
from pydantic import ValidationError

from app.runtime.events import ToolFailureKind
from app.runtime.limits import EffectiveLimits
from app.runtime.state import AgentState
from app.runtime.types import ToolGrant
from app.tools.base import ToolContext, ToolError
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

RESULT_PREVIEW_CHARS = 2_000
LIMIT_MESSAGE = "Error: tool call limit reached; this call was not executed."


class _ToolFailure(Exception):
    def __init__(self, kind: ToolFailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


def _summarize_validation(e: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}" for err in e.errors()
    )


def _preview(text: str) -> str:
    if len(text) <= RESULT_PREVIEW_CHARS:
        return text
    return text[:RESULT_PREVIEW_CHARS] + f"… [{len(text) - RESULT_PREVIEW_CHARS} more chars]"


class ToolNode:
    def __init__(
        self,
        registry: ToolRegistry,
        grants: list[ToolGrant],
        limits: EffectiveLimits,
        ctx: ToolContext,
    ) -> None:
        self.registry = registry
        self.grants = {g.name: g for g in grants}
        self.limits = limits
        self.ctx = ctx

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        write = get_stream_writer()
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        count = state.get("tool_call_count", 0)
        stop_reason: str | None = None
        out: list[ToolMessage] = []

        for call in last.tool_calls:
            call_id = call.get("id") or f"call_{uuid.uuid4().hex[:12]}"
            if count >= self.limits.max_tool_calls:
                # Answer every pending call so the stored history stays well-formed.
                stop_reason = "limit_exceeded"
                out.append(self._message(LIMIT_MESSAGE, call_id, call["name"], error=True))
                continue
            count += 1
            out.append(await self._execute(call, call_id, write))

        return {"messages": out, "tool_call_count": count, "stop_reason": stop_reason}

    @staticmethod
    def _message(content: str, call_id: str, name: str, *, error: bool) -> ToolMessage:
        return ToolMessage(
            content=content,
            tool_call_id=call_id,
            name=name,
            status="error" if error else "success",
            id=str(uuid.uuid4()),
        )

    async def _execute(self, call: ToolCall, call_id: str, write: Any) -> ToolMessage:
        name = call["name"]
        raw_args = call.get("args") or {}
        write(("tool.call.started", {"call_id": call_id, "tool": name, "args": raw_args}))
        started = time.perf_counter()
        try:
            result = await self._run(name, raw_args)
        except _ToolFailure as f:
            write(
                (
                    "tool.call.failed",
                    {"call_id": call_id, "tool": name, "error": f.message, "kind": f.kind},
                )
            )
            return self._message(f"Error: {f.message}", call_id, name, error=True)

        duration_ms = int((time.perf_counter() - started) * 1000)
        write(
            (
                "tool.call.completed",
                {
                    "call_id": call_id,
                    "tool": name,
                    "result": _preview(result),
                    "duration_ms": duration_ms,
                },
            )
        )
        return self._message(result, call_id, name, error=False)

    async def _run(self, name: str, raw_args: dict[str, Any]) -> str:
        grant = self.grants.get(name)
        if grant is None or name not in self.registry:
            raise _ToolFailure("permission", f"Tool '{name}' is not available to this agent")
        tool = self.registry.get(name)

        try:
            args = tool.parse_args(raw_args)
        except ValidationError as e:
            message = f"Invalid arguments: {_summarize_validation(e)}"
            raise _ToolFailure("validation", message) from None
        try:
            config = tool.parse_config(grant.config)
        except ValidationError:
            raise _ToolFailure("execution", "Tool is misconfigured for this agent") from None

        timeout = self.limits.tool_timeout(tool.timeout_s)
        try:
            return await asyncio.wait_for(tool.run(args, config, self.ctx), timeout=timeout)
        except TimeoutError:
            raise _ToolFailure("timeout", f"Tool timed out after {timeout:g}s") from None
        except ToolError as e:
            raise _ToolFailure("execution", str(e)) from None
        except Exception:
            logger.exception("Tool %s failed unexpectedly", name)
            raise _ToolFailure("execution", "Tool failed unexpectedly") from None
