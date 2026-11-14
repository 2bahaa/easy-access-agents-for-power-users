"""Small models sometimes wrap tool arguments in an echo of the function schema."""

from pathlib import Path

import pytest

from app.runtime.tool_node import unwrap_schema_echo
from app.runtime.types import ToolGrant
from tests.fakes import FakeChatModel, FakeProvider, reply, tool_call
from tests.unit.test_runtime import collect, make_config, make_run


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Observed from llama3.2:1b
        (
            {"type": "function", "function": "file_reader", "parameters": {"path": "notes.txt"}},
            {"path": "notes.txt"},
        ),
        ({"name": "calculator", "arguments": {"expression": "1+1"}}, {"expression": "1+1"}),
        ({"parameters": {"path": "a"}}, {"path": "a"}),
        # Left untouched:
        ({"path": "notes.txt"}, {"path": "notes.txt"}),  # normal arguments
        ({}, {}),
        ({"path": "x", "parameters": {"path": "y"}}, {"path": "x", "parameters": {"path": "y"}}),
        ({"parameters": "not-a-dict"}, {"parameters": "not-a-dict"}),
        (  # ambiguous: two candidate objects
            {"parameters": {"a": 1}, "arguments": {"b": 2}},
            {"parameters": {"a": 1}, "arguments": {"b": 2}},
        ),
    ],
)
def test_unwrap_schema_echo(raw: dict[str, object], expected: dict[str, object]) -> None:
    assert unwrap_schema_echo(raw) == expected


async def test_wrapped_arguments_still_respect_the_sandbox(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("The answer is 42.", encoding="utf-8")
    wrapped_ok = {
        "type": "function",
        "function": "file_reader",
        "parameters": {"path": "notes.txt"},
    }
    wrapped_escape = {"type": "function", "parameters": {"path": "../secret.txt"}}
    model = FakeChatModel(
        responses=[
            reply("", tool_call("file_reader", wrapped_ok)),
            reply("", tool_call("file_reader", wrapped_escape)),
            reply("Done."),
        ]
    )
    run = make_run(
        tmp_path,
        config=make_config(tools=[ToolGrant(name="file_reader")]),
        provider=FakeProvider(model),
    )
    events = await collect(run)
    completed = [e for e in events if e.type == "tool.call.completed"]
    failed = [e for e in events if e.type == "tool.call.failed"]
    assert [e.result for e in completed] == ["The answer is 42."]
    assert len(failed) == 1 and "must not contain '..'" in failed[0].error
