"""Phase 0 spike: can an Ollama model do streamed tool calling through LangGraph?

Throwaway script (not part of the app). Usage:
    uv run python scripts/spike_ollama_tools.py [model] [trials]

Checks:
  1. Ollama /api/show reports the "tools" capability.
  2. LangGraph custom StateGraph + ChatOllama.bind_tools streams tokens
     (stream_mode="messages") and custom tool events (stream_mode="custom").
  3. Reliability over N trials: tool called, args valid, correct final answer,
     and no spurious tool call on a prompt that needs no tool.
"""

from __future__ import annotations

import ast
import asyncio
import operator
import sys
import time
from typing import Annotated, Any, TypedDict

import httpx
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

OLLAMA = "http://localhost:11434"
EXPECTED = 406.5  # 17.5 * 23 + 4

_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def safe_eval(expr: str) -> float:
    def ev(n: ast.AST) -> float:
        if isinstance(n, ast.Constant) and isinstance(n.value, int | float):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return float(_OPS[type(n.op)](ev(n.left), ev(n.right)))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return float(_OPS[type(n.op)](ev(n.operand)))
        raise ValueError(f"unsupported expression: {expr!r}")

    return ev(ast.parse(expr, mode="eval").body)


CALC_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Evaluate an arithmetic expression, e.g. '2 * (3 + 4)'.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Arithmetic expression"}
            },
            "required": ["expression"],
        },
    },
}


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def build_graph(model: str) -> Any:
    llm = ChatOllama(model=model, base_url=OLLAMA, temperature=0).bind_tools([CALC_SCHEMA])

    async def agent(state: State) -> dict[str, Any]:
        return {"messages": [await llm.ainvoke(state["messages"])]}

    async def tools(state: State) -> dict[str, Any]:
        write = get_stream_writer()
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        out: list[ToolMessage] = []
        for call in last.tool_calls:
            write({"event": "tool.started", "tool": call["name"], "args": call["args"]})
            try:
                if call["name"] != "calculator":
                    raise PermissionError(f"tool not permitted: {call['name']}")
                result = str(safe_eval(str(call["args"]["expression"])))
                write({"event": "tool.completed", "result": result})
            except Exception as e:  # noqa: BLE001 - spike
                result = f"error: {e}"
                write({"event": "tool.failed", "error": str(e)})
            out.append(ToolMessage(content=result, tool_call_id=call["id"], name=call["name"]))
        return {"messages": out}

    def route(state: State) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else END

    g = StateGraph(State)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, ["tools", END])
    g.add_edge("tools", "agent")
    return g.compile()


async def run_once(graph: Any, prompt: str) -> dict[str, Any]:
    msgs = [
        SystemMessage("You are a helpful assistant. Use the calculator tool for any arithmetic."),
        HumanMessage(prompt),
    ]
    tokens, tool_events, final = 0, [], ""
    t0 = time.perf_counter()
    async for chunk in graph.astream(
        {"messages": msgs},
        stream_mode=["messages", "custom"],
        version="v2",
        config={"recursion_limit": 8},
    ):
        if chunk["type"] == "messages":
            msg, meta = chunk["data"]
            if meta.get("langgraph_node") == "agent" and msg.content:
                tokens += 1
                final += msg.content
        elif chunk["type"] == "custom":
            tool_events.append(chunk["data"])
    return {
        "tokens": tokens,
        "tool_events": tool_events,
        "final": final.strip(),
        "secs": round(time.perf_counter() - t0, 1),
    }


async def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "llama3.2:1b"
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    async with httpx.AsyncClient() as c:
        show = (await c.post(f"{OLLAMA}/api/show", json={"model": model})).json()
    caps = show.get("capabilities", [])
    print(f"model={model} capabilities={caps}")

    graph = build_graph(model)
    ok_tool = ok_answer = streamed = 0
    for i in range(trials):
        r = await run_once(graph, "What is 17.5 * 23 + 4?")
        called = any(
            e["event"] == "tool.completed" and float(e["result"]) == EXPECTED
            for e in r["tool_events"]
            if e["event"] == "tool.completed"
        )
        correct = "406.5" in r["final"]
        ok_tool += called
        ok_answer += correct
        streamed += r["tokens"] > 1
        print(
            f"[math {i + 1}] tool_ok={called} answer_ok={correct} tokens={r['tokens']} "
            f"{r['secs']}s events={r['tool_events']} final={r['final'][:120]!r}"
        )

    spurious = 0
    for i in range(trials):
        r = await run_once(graph, "Say hello in one short sentence.")
        spurious += bool(r["tool_events"])
        print(f"[chat {i + 1}] tool_events={r['tool_events']} final={r['final'][:80]!r}")

    print("\nSUMMARY")
    print(f"  tools capability advertised : {'tools' in caps}")
    print(f"  correct tool call           : {ok_tool}/{trials}")
    print(f"  correct final answer        : {ok_answer}/{trials}")
    print(f"  token streaming observed    : {streamed}/{trials}")
    print(f"  spurious tool calls (chat)  : {spurious}/{trials}")


if __name__ == "__main__":
    asyncio.run(main())
