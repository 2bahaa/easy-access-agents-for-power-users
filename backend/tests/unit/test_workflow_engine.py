"""Workflow spec validation, the expression sandbox and the engine (fake services, no DB)."""

import asyncio
import uuid
from typing import Any

import pytest

from app.runtime.events import AgentEvent
from app.runtime.workflow.engine import NodeError, WorkflowResume, WorkflowRun
from app.runtime.workflow.expressions import ExpressionError, evaluate, render
from app.runtime.workflow.spec import WorkflowSpec, validate_structure

AGENT = str(uuid.uuid4())


def n(nid: str, ntype: str, **config: Any) -> dict[str, Any]:
    return {"id": nid, "type": ntype, "config": config}


def spec(
    nodes: list[dict[str, Any]], edges: list[tuple[str, str] | tuple[str, str, str]]
) -> WorkflowSpec:
    return WorkflowSpec.model_validate(
        {
            "nodes": nodes,
            "edges": [
                {"source": e[0], "target": e[1], "source_handle": e[2] if len(e) > 2 else None}
                for e in edges
            ],
        }
    )


START = n("start", "start", inputs=[{"name": "text"}])
END = n("end", "end", output="{{ b }}")


def linear() -> WorkflowSpec:
    return spec(
        [
            START,
            n("a", "llm", model="m", prompt="Upper: {{ input.text }}"),
            n("b", "llm", model="m", prompt="Twice: {{ a }}"),
            END,
        ],
        [("start", "a"), ("a", "b"), ("b", "end")],
    )


def messages(problems: list[Any]) -> list[str]:
    return [p.message for p in problems]


# ---- validation ---------------------------------------------------------------------------------


def test_valid_linear_spec() -> None:
    assert validate_structure(linear()) == []


@pytest.mark.parametrize(
    ("nodes", "edges", "expected"),
    [
        ([END], [], "exactly one Start"),
        ([START, n("s2", "start"), END], [("start", "end"), ("s2", "end")], "exactly one Start"),
        ([START], [], "at least one End"),
        ([START, n("x", "llm", model="m", prompt="p"), END], [("start", "end")], "Not connected"),
        (
            [
                START,
                n("a", "llm", model="m", prompt="p"),
                n("b", "llm", model="m", prompt="p"),
                END,
            ],
            [("start", "a"), ("a", "b"), ("b", "a"), ("b", "end")],
            "Parallel",
        ),
        (
            [START, n("a", "llm", model="m", prompt="p"), END],
            [("start", "a"), ("a", "end"), ("end", "a")],
            "End has no outgoing",
        ),
        (
            [START, n("c", "condition", expression="true"), END],
            [("start", "c"), ("c", "end", "true")],
            "both branches",
        ),
        (
            [START, n("r", "router", model="m", routes=["a", "b"], input="x"), END],
            [("start", "r"), ("r", "end", "zzz")],
            "router edge",
        ),
        (
            [
                START,
                n("a", "llm", model="m", prompt="{{ later }}"),
                n("later", "llm", model="m", prompt="p"),
                END,
            ],
            [("start", "a"), ("a", "later"), ("later", "end")],
            "not an earlier step",
        ),
        (
            [START, n("a", "llm", model="m", prompt="{{ input.nope }}"), END],
            [("start", "a"), ("a", "end")],
            "Unknown input",
        ),
        (
            [START, n("c", "condition", expression="__import__('os')"), END, n("e2", "end")],
            [("start", "c"), ("c", "end", "true"), ("c", "e2", "false")],
            "are allowed",
        ),
        (
            [START, n("input", "llm", model="m", prompt="p"), END],
            [("start", "input"), ("input", "end")],
            "reserved",
        ),
        ([START, n("a", "llm", prompt="p"), END], [("start", "a"), ("a", "end")], "model"),
    ],
)
def test_structure_problems(nodes: list[dict[str, Any]], edges: list[Any], expected: str) -> None:
    problems = validate_structure(spec(nodes, edges))
    assert any(expected in m for m in messages(problems)), messages(problems)


def test_cycles_are_rejected() -> None:
    nodes = [START, n("p", "parallel"), n("a", "llm", model="m", prompt="p"), END]
    problems = validate_structure(
        spec(nodes, [("start", "p"), ("p", "a"), ("p", "end"), ("a", "p")])
    )
    assert "loops" in " ".join(messages(problems))


# ---- expressions ---------------------------------------------------------------------


def test_expressions() -> None:
    outs = {"classify": "This is URGENT", "score": "8"}
    inputs = {"priority": "high"}
    assert evaluate('contains(classify, "urgent") and number(score) >= 7', outs, inputs)
    assert evaluate('input_priority == "high" or false', outs, inputs) is True
    assert evaluate("not startswith(classify, 'nope')", outs, inputs)
    assert evaluate("len(classify) > 3 and lower(classify) != classify", outs, inputs)
    assert (
        render("A={{ classify }} P={{ input.priority }} X={{ missing }}", outs, inputs)
        == "A=This is URGENT P=high X="
    )


@pytest.mark.parametrize(
    "expression",
    [
        "classify.__class__",
        "open('x')",
        "[x for x in classify]",
        "classify[0]",
        "lambda: 1",
        "(1).real",
        "__import__('os').system('rm -rf /')",
        "contains(classify, b'x')",
        " or ".join(["x"] * 40),
    ],
)
def test_expression_sandbox(expression: str) -> None:
    with pytest.raises(ExpressionError):
        evaluate(expression, {"classify": "x", "x": "1"}, {})


def test_number_conversion_errors() -> None:
    with pytest.raises(ExpressionError):
        evaluate("number(x) > 1", {"x": "not a number"}, {})


# ---- engine --------------------------------------------------------------------------


class FakeServices:
    def __init__(
        self, *, fail: set[str] | None = None, delay: float = 0.0, router_answer: str = "question"
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail or set()
        self.delay = delay
        self.router_answer = router_answer

    async def run_agent(self, agent_id: uuid.UUID, prompt: str, use_draft: bool) -> str:
        self.calls.append(("agent", prompt))
        return f"agent says: {prompt}"

    async def call_llm(
        self,
        provider: str,
        connection_id: Any,
        model: str,
        system: str,
        prompt: str,
        temperature: Any,
    ) -> str:
        if "Classify" in system:
            return self.router_answer
        self.calls.append(("llm", prompt))
        if self.delay:
            await asyncio.sleep(self.delay)
        if any(f in prompt for f in self.fail):
            raise NodeError("the model is down")
        return prompt.upper()

    async def run_tool(self, tool: str, args: dict[str, Any], config: dict[str, Any]) -> str:
        self.calls.append(("tool", str(args)))
        return "42"

    async def search_knowledge(
        self, collection_ids: list[uuid.UUID], query: str, top_k: int
    ) -> str:
        return f"passages for {query}"

    async def memory(self, agent_id: uuid.UUID, action: str, text: str) -> str:
        return "ok"


async def run(
    wf: WorkflowSpec, services: FakeServices, inputs: dict[str, str] | None = None, **kw: Any
) -> tuple[WorkflowRun, list[AgentEvent]]:
    r = WorkflowRun(uuid.uuid4(), wf, inputs or {"text": "hi"}, services, **kw)
    events = [e async for e in r.stream()]
    return r, events


async def test_linear_workflow() -> None:
    r, events = await run(linear(), FakeServices())
    assert r.result.status == "completed"
    assert r.result.output == "TWICE: UPPER: HI"
    types = [e.type for e in events]
    assert types[0] == "run.started" and types[-1] == "run.completed"
    assert [e.node_id for e in events if e.type == "node.completed"] == ["start", "a", "b", "end"]  # type: ignore[attr-defined]
    assert [e.seq for e in events] == list(range(1, len(events) + 1))


async def test_condition_branches() -> None:
    nodes = [
        START,
        n("c", "condition", expression='contains(input_text, "yes")'),
        n("y", "llm", model="m", prompt="yes path"),
        n("no", "llm", model="m", prompt="no path"),
        n("end", "end", output="{{ y }}{{ no }}"),
    ]
    edges = [("start", "c"), ("c", "y", "true"), ("c", "no", "false"), ("y", "end"), ("no", "end")]
    wf = spec(nodes, edges)
    assert validate_structure(wf) == []
    r, _ = await run(wf, FakeServices(), {"text": "yes please"})
    assert r.result.output == "YES PATH"
    r, _ = await run(wf, FakeServices(), {"text": "never"})
    assert r.result.output == "NO PATH"


async def test_router_routes_by_label() -> None:
    nodes = [
        START,
        n("r", "router", model="m", routes=["question", "complaint"], input="{{ input.text }}"),
        n("q", "llm", model="m", prompt="answer"),
        n("c", "llm", model="m", prompt="apologize"),
        n("end", "end", output="{{ q }}{{ c }}"),
    ]
    wf = spec(
        nodes,
        [
            ("start", "r"),
            ("r", "q", "question"),
            ("r", "c", "complaint"),
            ("q", "end"),
            ("c", "end"),
        ],
    )
    r, _ = await run(wf, FakeServices(router_answer="Complaint."))
    assert r.result.output == "APOLOGIZE"
    r, _ = await run(wf, FakeServices(router_answer="banana"))
    assert r.result.status == "failed" and "not one of" in (r.result.error or "")


async def test_parallel_fan_out_and_join() -> None:
    nodes = [
        START,
        n("p", "parallel"),
        n("a", "llm", model="m", prompt="left"),
        n("b", "llm", model="m", prompt="right"),
        n("merge", "llm", model="m", prompt="{{ a }}+{{ b }}"),
        n("end", "end", output="{{ merge }}"),
    ]
    wf = spec(
        nodes,
        [("start", "p"), ("p", "a"), ("p", "b"), ("a", "merge"), ("b", "merge"), ("merge", "end")],
    )
    assert validate_structure(wf) == []
    services = FakeServices(delay=0.05)
    r, events = await run(wf, services)
    assert r.result.output in ("LEFT+RIGHT", "RIGHT+LEFT".replace("RIGHT+LEFT", "LEFT+RIGHT"))
    merged = [e for e in events if e.type == "node.completed" and e.node_id == "merge"]  # type: ignore[attr-defined]
    assert len(merged) == 1  # the join runs once, after both branches


async def test_agent_tool_knowledge_nodes() -> None:
    nodes = [
        START,
        n("ag", "agent", agent_id=AGENT, prompt="Research {{ input.text }}"),
        n("t", "tool", tool="calculator", args={"expression": "6*7"}),
        n("k", "knowledge", collection_ids=[AGENT], query="{{ ag }}"),
        n("end", "end", output="{{ t }} / {{ k }}"),
    ]
    wf = spec(nodes, [("start", "ag"), ("ag", "t"), ("t", "k"), ("k", "end")])
    r, _ = await run(wf, FakeServices())
    assert r.result.output == "42 / passages for agent says: Research hi"


async def test_approval_pauses_and_resumes() -> None:
    nodes = [
        START,
        n("draft", "llm", model="m", prompt="draft"),
        n("ok", "approval", message="Publish {{ draft }}?"),
        n("pub", "end", output="published {{ draft }}"),
        n("rej", "end", output="rejected"),
    ]
    wf = spec(
        nodes,
        [("start", "draft"), ("draft", "ok"), ("ok", "pub", "approved"), ("ok", "rej", "rejected")],
    )
    assert validate_structure(wf) == []
    services = FakeServices()
    r, events = await run(wf, services)
    assert r.result.status == "waiting_approval"
    assert r.result.pending == {"node_id": "ok", "message": "Publish DRAFT?"}
    assert events[-1].type == "run.waiting_approval"
    saved = r.result.outputs

    r2, _ = await run(
        wf, services, resume=WorkflowResume(node_id="ok", approved=True, outputs=saved)
    )
    assert (r2.result.status, r2.result.output) == ("completed", "published DRAFT")
    assert [c for c in services.calls if c == ("llm", "draft")] == [("llm", "draft")]  # not re-run
    r3, _ = await run(
        wf, services, resume=WorkflowResume(node_id="ok", approved=False, outputs=saved, note="no")
    )
    assert r3.result.output == "rejected"


async def test_node_failure_fails_the_run() -> None:
    r, events = await run(linear(), FakeServices(fail={"Twice"}))
    assert r.result.status == "failed"
    failed = [e for e in events if e.type == "node.failed"]
    assert [e.node_id for e in failed] == ["b"]  # type: ignore[attr-defined]
    assert events[-1].type == "run.failed" and events[-1].code == "node_failed"  # type: ignore[attr-defined]


async def test_timeout_and_cancel() -> None:
    r, events = await run(linear(), FakeServices(delay=1.0), timeout_s=0.2)
    assert r.result.status == "timeout" and events[-1].type == "run.failed"

    wr = WorkflowRun(uuid.uuid4(), linear(), {"text": "x"}, FakeServices(delay=5))
    collected: list[AgentEvent] = []

    async def consume() -> None:
        async for e in wr.stream():
            collected.append(e)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.2)
    wr.cancel()
    await asyncio.wait_for(task, timeout=5)
    assert wr.result.status == "cancelled" and collected[-1].type == "run.cancelled"
