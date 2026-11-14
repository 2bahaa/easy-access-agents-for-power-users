import uuid

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.db.models import Message
from app.services.run_service import UNFINISHED_TOOL_CALL, _with_answered_tool_calls, to_langchain


def test_db_rows_to_langchain() -> None:
    conv = uuid.uuid4()
    rows = [
        Message(id=uuid.uuid4(), conversation_id=conv, seq=1, role="user", content="q"),
        Message(
            id=uuid.uuid4(),
            conversation_id=conv,
            seq=2,
            role="assistant",
            content="",
            tool_calls=[{"id": "c1", "name": "calculator", "args": {"expression": "1+1"}}],
        ),
        Message(
            id=uuid.uuid4(),
            conversation_id=conv,
            seq=3,
            role="tool",
            content="2",
            tool_call_id="c1",
            tool_name="calculator",
        ),
        Message(id=uuid.uuid4(), conversation_id=conv, seq=4, role="assistant", content="2!"),
    ]
    human, ai, tool, final = to_langchain(rows)
    assert isinstance(human, HumanMessage) and human.content == "q"
    assert isinstance(ai, AIMessage) and ai.tool_calls[0]["args"] == {"expression": "1+1"}
    assert isinstance(tool, ToolMessage) and tool.tool_call_id == "c1" and tool.name == "calculator"
    assert isinstance(final, AIMessage) and final.tool_calls == []
    assert human.id == str(rows[0].id)


def test_unanswered_tool_calls_get_error_results() -> None:
    ai = AIMessage(
        "",
        tool_calls=[
            {"id": "a", "name": "calculator", "args": {}},
            {"id": "b", "name": "calculator", "args": {}},
        ],
    )
    done = ToolMessage("2", tool_call_id="a", name="calculator")
    fixed = _with_answered_tool_calls([ai, done])
    assert len(fixed) == 3
    added = fixed[-1]
    assert isinstance(added, ToolMessage)
    assert (added.tool_call_id, added.content, added.status) == ("b", UNFINISHED_TOOL_CALL, "error")
    # Already-complete histories are unchanged.
    assert _with_answered_tool_calls([ai, done, fixed[-1]]) == [ai, done, fixed[-1]]
