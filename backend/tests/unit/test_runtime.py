"""Agent runtime behavior with a scripted fake model (no Ollama, no DB)."""

import asyncio
import contextlib
import uuid
from pathlib import Path
from typing import Any, ClassVar

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

from app.runtime.events import TERMINAL_TYPES, AgentEvent, agent_event_adapter
from app.runtime.executor import AgentRun
from app.runtime.limits import effective_limits
from app.runtime.types import AgentConfig, RunRequest, RuntimeCaps, SkillContent, ToolGrant
from app.tools.base import EmptyConfig, Tool, ToolContext
from app.tools.registry import ToolRegistry, build_default_registry
from tests.fakes import FakeChatModel, FakeProvider, reply, tool_call

CAPS = RuntimeCaps(max_tool_calls=20, run_timeout_s=30, tool_timeout_s=5)
CALC = ToolGrant(name="calculator")


class SleepArgs(BaseModel):
    seconds: float = 10


class SleepTool(Tool[SleepArgs, EmptyConfig]):
    name: ClassVar[str] = "sleep"
    description: ClassVar[str] = "Sleeps"
    args_model = SleepArgs
    config_model = EmptyConfig

    async def run(self, args: SleepArgs, config: EmptyConfig, ctx: ToolContext) -> str:
        await asyncio.sleep(args.seconds)
        return "woke up"


def make_config(**overrides: Any) -> AgentConfig:
    values: dict[str, Any] = {
        "agent_id": uuid.uuid4(),
        "name": "Test agent",
        "provider": "ollama",
        "model": "fake:1b",
        "system_prompt": "You are a test agent.",
        "tools": [CALC],
    }
    return AgentConfig(**(values | overrides))


def make_run(
    tmp_path: Path,
    responses: list[AIMessage] | None = None,
    *,
    config: AgentConfig | None = None,
    provider: FakeProvider | None = None,
    registry: ToolRegistry | None = None,
    caps: RuntimeCaps = CAPS,
    history: list[BaseMessage] | None = None,
) -> AgentRun:
    provider = provider or FakeProvider(FakeChatModel(responses=list(responses or [])))
    request = RunRequest(
        run_id=uuid.uuid4(),
        config=config or make_config(),
        history=history or [HumanMessage("hi")],
    )
    return AgentRun(
        request, provider, registry or build_default_registry(), caps, ToolContext(tmp_path)
    )


async def collect(run: AgentRun) -> list[AgentEvent]:
    events = [e async for e in run.stream()]
    # Protocol invariants that must hold for every run.
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert events[0].type == "run.started"
    assert sum(e.type in TERMINAL_TYPES for e in events) == 1
    assert events[-1].type in TERMINAL_TYPES
    for e in events:
        assert agent_event_adapter.validate_json(agent_event_adapter.dump_json(e)) == e
    return events


def types(events: list[AgentEvent]) -> list[str]:
    return [e.type for e in events]


def of_type(events: list[AgentEvent], event_type: str) -> list[Any]:
    return [e for e in events if e.type == event_type]


async def test_text_answer_streams_tokens(tmp_path: Path) -> None:
    run = make_run(tmp_path, [reply("Hello there, human!")])
    events = await collect(run)

    deltas = of_type(events, "message.delta")
    assert len(deltas) == 3
    assert "".join(d.text for d in deltas) == "Hello there, human!"
    (completed,) = of_type(events, "message.completed")
    assert completed.content == "Hello there, human!"
    assert events[-1].type == "run.completed"
    assert run.result.status == "completed"
    assert run.result.usage == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    assert [type(m) for m in run.result.new_messages] == [AIMessage]
    assert run.result.new_messages[0].id == completed.message_id


async def test_calculator_tool_round_trip(tmp_path: Path) -> None:
    model = FakeChatModel(
        responses=[
            reply("", tool_call("calculator", {"expression": "17.5 * 23 + 4"}, "c1")),
            reply("The answer is 406.5."),
        ]
    )
    run = make_run(tmp_path, provider=FakeProvider(model))
    events = await collect(run)

    assert types(events)[:3] == ["run.started", "tool.call.started", "tool.call.completed"]
    started, done = events[1], events[2]
    assert (started.call_id, started.tool, started.args) == (
        "c1",
        "calculator",
        {"expression": "17.5 * 23 + 4"},
    )
    assert (done.call_id, done.result) == ("c1", "406.5")
    assert of_type(events, "message.completed")[0].content == "The answer is 406.5."
    assert run.result.tool_call_count == 1
    assert run.result.usage["total_tokens"] == 30

    ai, tool_msg, final = run.result.new_messages
    assert isinstance(ai, AIMessage) and ai.tool_calls[0]["id"] == "c1"
    assert isinstance(tool_msg, ToolMessage) and tool_msg.content == "406.5"
    assert tool_msg.tool_call_id == "c1" and tool_msg.status == "success"
    assert isinstance(final, AIMessage)
    # The second LLM call saw the tool result.
    assert any(isinstance(m, ToolMessage) and m.content == "406.5" for m in model.prompts[1])


async def test_only_permitted_tools_are_bound(tmp_path: Path) -> None:
    model = FakeChatModel(responses=[reply("ok")])
    await collect(make_run(tmp_path, provider=FakeProvider(model)))
    assert model.bound_tools is not None
    assert [t["function"]["name"] for t in model.bound_tools] == ["calculator"]

    plain = FakeChatModel(responses=[reply("ok")])
    await collect(make_run(tmp_path, config=make_config(tools=[]), provider=FakeProvider(plain)))
    assert plain.bound_tools is None


async def test_unpermitted_tool_call_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("secret", encoding="utf-8")
    run = make_run(
        tmp_path,
        [reply("", tool_call("file_reader", {"path": "notes.txt"}, "c1")), reply("Sorry.")],
    )
    events = await collect(run)
    (failed,) = of_type(events, "tool.call.failed")
    assert (failed.kind, failed.tool) == ("permission", "file_reader")
    assert not of_type(events, "tool.call.completed")
    tool_msg = run.result.new_messages[1]
    assert isinstance(tool_msg, ToolMessage) and tool_msg.status == "error"
    assert "secret" not in str(tool_msg.content)
    assert run.result.status == "completed"


@pytest.mark.parametrize(
    ("args", "kind", "message"),
    [
        ({"expr": "1+1"}, "validation", "Invalid arguments"),
        ({"expression": "1/0"}, "execution", "Division by zero"),
        ({"expression": "__import__('os')"}, "execution", "Unsupported syntax"),
    ],
)
async def test_tool_failures_are_returned_to_model(
    tmp_path: Path, args: dict[str, Any], kind: str, message: str
) -> None:
    model = FakeChatModel(responses=[reply("", tool_call("calculator", args)), reply("Recovered.")])
    run = make_run(tmp_path, provider=FakeProvider(model))
    events = await collect(run)
    (failed,) = of_type(events, "tool.call.failed")
    assert failed.kind == kind and message in failed.error
    tool_msgs = [m for m in model.prompts[1] if isinstance(m, ToolMessage)]
    assert tool_msgs and message in str(tool_msgs[0].content)
    assert run.result.status == "completed"


async def test_tool_timeout(tmp_path: Path) -> None:
    run = make_run(
        tmp_path,
        [reply("", tool_call("sleep", {"seconds": 5})), reply("done")],
        config=make_config(tools=[ToolGrant(name="sleep")]),
        registry=ToolRegistry([SleepTool()]),
        caps=RuntimeCaps(max_tool_calls=5, run_timeout_s=30, tool_timeout_s=0.05),
    )
    events = await collect(run)
    (failed,) = of_type(events, "tool.call.failed")
    assert failed.kind == "timeout"
    assert run.result.status == "completed"


async def test_max_tool_calls_across_turns(tmp_path: Path) -> None:
    calls = [reply("", tool_call("calculator", {"expression": f"{i}+1"})) for i in range(5)]
    run = make_run(tmp_path, calls, config=make_config(max_tool_calls=2))
    events = await collect(run)
    assert len(of_type(events, "tool.call.started")) == 2
    (failed,) = of_type(events, "run.failed")
    assert failed.code == "limit_exceeded"
    assert run.result.status == "limit_exceeded"
    assert run.result.tool_call_count == 2
    last = run.result.new_messages[-1]
    assert isinstance(last, ToolMessage) and "limit reached" in str(last.content)


async def test_max_tool_calls_within_one_message(tmp_path: Path) -> None:
    many = reply("", *(tool_call("calculator", {"expression": "1+1"}) for _ in range(3)))
    run = make_run(tmp_path, [many], config=make_config(max_tool_calls=2))
    events = await collect(run)
    assert len(of_type(events, "tool.call.completed")) == 2
    assert run.result.status == "limit_exceeded"
    # Every tool call has an answer, so the stored history stays valid.
    tool_msgs = [m for m in run.result.new_messages if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 3


async def test_agent_limit_is_clamped_to_global_cap(tmp_path: Path) -> None:
    calls = [reply("", tool_call("calculator", {"expression": "1+1"})) for _ in range(3)]
    caps = RuntimeCaps(max_tool_calls=1, run_timeout_s=30, tool_timeout_s=5)
    run = make_run(tmp_path, calls, config=make_config(max_tool_calls=8), caps=caps)
    await collect(run)
    assert run.result.tool_call_count == 1
    assert run.result.status == "limit_exceeded"


def test_effective_limits() -> None:
    limits = effective_limits(make_config(max_tool_calls=50, run_timeout_s=999), CAPS)
    assert (limits.max_tool_calls, limits.run_timeout_s) == (20, 30)
    assert limits.recursion_limit == 43
    assert limits.tool_timeout(2.0) == 2.0
    assert limits.tool_timeout(60.0) == 5
    assert limits.tool_timeout(None) == 5


async def test_run_timeout(tmp_path: Path) -> None:
    model = FakeChatModel(responses=[reply("too slow")], delay_s=2)
    caps = RuntimeCaps(max_tool_calls=5, run_timeout_s=0.05, tool_timeout_s=5)
    run = make_run(tmp_path, provider=FakeProvider(model), caps=caps)
    events = await collect(run)
    assert events[-1].type == "run.failed" and events[-1].code == "timeout"
    assert run.result.status == "timeout"


async def test_model_without_tool_support_is_blocked(tmp_path: Path) -> None:
    provider = FakeProvider(FakeChatModel(responses=[reply("hi")]), no_tool_models={"fake:1b"})
    run = make_run(tmp_path, provider=provider)
    events = await collect(run)
    assert types(events) == ["run.started", "run.failed"]
    assert events[-1].code == "model_no_tool_support"
    assert provider.created == []  # no model was even built

    # The same model is fine for an agent without tools.
    ok = make_run(tmp_path, config=make_config(tools=[]), provider=provider)
    assert (await collect(ok))[-1].type == "run.completed"


async def test_missing_model_is_provider_error(tmp_path: Path) -> None:
    provider = FakeProvider(missing_models={"fake:1b"})
    events = await collect(make_run(tmp_path, provider=provider))
    assert events[-1].code == "provider_error"
    assert "not available" in events[-1].message


async def test_provider_failure_during_call(tmp_path: Path) -> None:
    model = FakeChatModel(error=ConnectionError("connection refused"))
    run = make_run(tmp_path, provider=FakeProvider(model))
    events = await collect(run)
    assert events[-1].code == "provider_error"
    assert run.result.status == "failed"


async def test_unexpected_error_is_internal_and_sanitized(tmp_path: Path) -> None:
    model = FakeChatModel(error=ValueError("secret stack detail"))
    run = make_run(tmp_path, provider=FakeProvider(model))
    events = await collect(run)
    assert events[-1].code == "internal_error"
    assert "secret" not in events[-1].message


async def test_system_prompt_includes_skills_and_history(tmp_path: Path) -> None:
    model = FakeChatModel(responses=[reply("ok")])
    config = make_config(
        skills=[SkillContent(slug="be-brief", name="Be brief", content_md="Use few words.")]
    )
    history: list[BaseMessage] = [
        HumanMessage("first"),
        AIMessage("first answer"),
        HumanMessage("second"),
    ]
    await collect(make_run(tmp_path, config=config, provider=FakeProvider(model), history=history))
    system, *rest = model.prompts[0]
    assert isinstance(system, SystemMessage)
    assert str(system.content).startswith("You are a test agent.")
    assert "### Be brief\n\nUse few words." in str(system.content)
    assert [m.content for m in rest] == ["first", "first answer", "second"]


async def test_reasoning_is_streamed_separately(tmp_path: Path) -> None:
    events = await collect(make_run(tmp_path, [reply("Answer", reasoning="Let me think")]))
    assert [e.text for e in of_type(events, "reasoning.delta")] == ["Let me think"]
    assert of_type(events, "message.completed")[0].content == "Answer"


async def test_consumer_disconnect_cancels_run(tmp_path: Path) -> None:
    run = make_run(
        tmp_path,
        [reply("", tool_call("sleep", {"seconds": 10})), reply("never")],
        config=make_config(tools=[ToolGrant(name="sleep")]),
        registry=ToolRegistry([SleepTool()]),
        caps=RuntimeCaps(max_tool_calls=5, run_timeout_s=30, tool_timeout_s=30),
    )
    async with contextlib.aclosing(run.stream()) as stream:
        async for event in stream:
            if event.type == "tool.call.started":
                break
    assert run.result.status == "cancelled"


async def test_cancel_ends_stream_with_cancelled_event(tmp_path: Path) -> None:
    run = make_run(
        tmp_path,
        [reply("", tool_call("sleep", {"seconds": 10})), reply("never")],
        config=make_config(tools=[ToolGrant(name="sleep")]),
        registry=ToolRegistry([SleepTool()]),
        caps=RuntimeCaps(max_tool_calls=5, run_timeout_s=30, tool_timeout_s=30),
    )
    events: list[AgentEvent] = []
    async for event in run.stream():
        events.append(event)
        if event.type == "tool.call.started":
            run.cancel()
    assert events[-1].type == "run.cancelled"
    assert run.result.status == "cancelled"


def test_token_deltas_are_not_persisted() -> None:
    from app.runtime.events import MessageDelta, ReasoningDelta, RunStarted, ToolCallStarted

    assert not MessageDelta.persisted and not ReasoningDelta.persisted
    assert RunStarted.persisted and ToolCallStarted.persisted


async def test_large_token_chunks_are_split_into_bounded_deltas(tmp_path: Path) -> None:
    from app.runtime.events import MessageDelta
    from app.runtime.executor import MAX_DELTA_CHARS

    big = "y" * (MAX_DELTA_CHARS * 2 + 10)  # one word: the fake streams it as one chunk
    events = await collect(make_run(tmp_path, [reply(big)]))
    deltas = [e for e in events if isinstance(e, MessageDelta)]
    assert len(deltas) == 3
    assert all(len(e.text) <= MAX_DELTA_CHARS for e in deltas)
    assert "".join(e.text for e in deltas) == big


async def test_granted_but_unavailable_tool_is_not_bound_and_is_rejected(tmp_path: Path) -> None:
    """A grant for a tool missing from the run's registry (e.g. an MCP tool disabled after it
    was granted) must not crash the run: it is not bound, and calls are refused."""
    from app.runtime.events import ToolCallFailed

    config = make_config(tools=[ToolGrant(name="calculator"), ToolGrant(name="mcp__gone__tool")])
    provider = FakeProvider(
        FakeChatModel(responses=[reply("", tool_call("mcp__gone__tool", {}, "g")), reply("ok")])
    )
    events = await collect(make_run(tmp_path, config=config, provider=provider))
    assert events[-1].type == "run.completed"
    failed = [e for e in events if isinstance(e, ToolCallFailed)]
    assert [(f.tool, f.kind) for f in failed] == [("mcp__gone__tool", "permission")]
    bound = {t["function"]["name"] for t in provider.model.bound_tools or []}
    assert bound == {"calculator"}
