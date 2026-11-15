"""Multi-agent supervisor nodes and node-level resilience (retries, continue-on-error)."""

import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from app.runtime.workflow.engine import NodeError, WorkflowRun
from app.runtime.workflow.spec import WorkflowSpec, validate_structure
from tests.unit.test_workflow_engine import FakeServices

RESEARCHER, WRITER = str(uuid.uuid4()), str(uuid.uuid4())


def call(name: str, **args: Any) -> dict[str, Any]:
    return {"name": name, "args": args, "id": f"c_{uuid.uuid4().hex[:6]}"}


class TeamServices(FakeServices):
    def __init__(self, replies: list[AIMessage], fail_agents: set[str] | None = None) -> None:
        super().__init__()
        self.replies = list(replies)
        self.fail_agents = fail_agents or set()
        self.member_tasks: list[tuple[str, str]] = []
        self.transcripts: list[list[BaseMessage]] = []

    async def run_agent(self, agent_id: uuid.UUID, prompt: str, use_draft: bool) -> str:
        self.member_tasks.append((str(agent_id), prompt))
        if str(agent_id) in self.fail_agents:
            raise NodeError("member crashed")
        return f"result of: {prompt}"

    async def chat(
        self,
        provider: str,
        connection_id: Any,
        model: str,
        messages: list[BaseMessage],
        tools: list[dict[str, Any]],
    ) -> AIMessage:
        self.transcripts.append(list(messages))
        return (
            self.replies.pop(0)
            if self.replies
            else AIMessage(
                content="", tool_calls=[call("delegate", member="researcher", task="again")]
            )
        )


def team_spec(**config: Any) -> WorkflowSpec:
    base = {
        "model": "m",
        "task": "Write about {{ input.text }}",
        "members": [
            {"name": "researcher", "agent_id": RESEARCHER, "role": "finds facts"},
            {"name": "writer", "agent_id": WRITER, "role": "writes prose"},
        ],
        "max_delegations": 3,
    }
    return WorkflowSpec.model_validate(
        {
            "nodes": [
                {"id": "start", "type": "start", "config": {"inputs": [{"name": "text"}]}},
                {"id": "team", "type": "supervisor", "config": base | config},
                {"id": "end", "type": "end", "config": {"output": "{{ team }}"}},
            ],
            "edges": [{"source": "start", "target": "team"}, {"source": "team", "target": "end"}],
        }
    )


async def run(spec: WorkflowSpec, services: FakeServices) -> tuple[WorkflowRun, list[Any]]:
    r = WorkflowRun(uuid.uuid4(), spec, {"text": "tides"}, services)
    return r, [e async for e in r.stream()]


async def test_supervisor_delegates_and_finishes() -> None:
    services = TeamServices(
        [
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "delegate",
                        member="researcher",
                        task="Find tide facts",
                        reason="needs facts",
                    )
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "delegate", member="writer", task="Write a paragraph", reason="needs prose"
                    )
                ],
            ),
            AIMessage(
                content="", tool_calls=[call("finish", answer="A great paragraph about tides.")]
            ),
        ]
    )
    spec = team_spec()
    assert validate_structure(spec) == []
    r, events = await run(spec, services)
    assert r.result.output == "A great paragraph about tides."
    delegated = [(e.member, e.reason) for e in events if e.type == "agent.delegated"]
    assert delegated == [("researcher", "needs facts"), ("writer", "needs prose")]
    assert [e.ok for e in events if e.type == "agent.result"] == [True, True]
    # Context isolation: members only see their own task.
    assert services.member_tasks == [(RESEARCHER, "Find tide facts"), (WRITER, "Write a paragraph")]
    # The supervisor saw each member's result before deciding.
    last = services.transcripts[-1]
    assert "result of: Write a paragraph" in str(last[-1].content)


async def test_shared_task_and_direct_answers() -> None:
    services = TeamServices(
        [
            AIMessage(content="", tool_calls=[call("delegate", member="researcher", task="facts")]),
            AIMessage(content="Done directly."),
        ]
    )
    r, _ = await run(team_spec(share_task_with_members=True), services)
    assert r.result.output == "Done directly."
    assert services.member_tasks[0][1].startswith("Overall goal: Write about tides")


async def test_delegation_budget_unknown_members_and_failures() -> None:
    services = TeamServices(
        [
            AIMessage(content="", tool_calls=[call("delegate", member="ghost", task="x")]),
            AIMessage(content="", tool_calls=[call("delegate", member="researcher", task="a")]),
            AIMessage(content="", tool_calls=[call("delegate", member="researcher", task="b")]),
            AIMessage(content="", tool_calls=[call("finish", answer="ok")]),
        ],
        fail_agents={RESEARCHER},
    )
    r, events = await run(team_spec(max_delegations=1), services)
    assert r.result.output == "ok"
    assert len([e for e in events if e.type == "agent.delegated"]) == 1  # budget enforced
    assert [e.ok for e in events if e.type == "agent.result"] == [
        False
    ]  # failure reported, not fatal
    tool_texts = " ".join(str(m.content) for m in services.transcripts[-1] if m.type == "tool")
    assert "no member named 'ghost'" in tool_texts and "delegation limit reached" in tool_texts

    endless = TeamServices([])  # always delegates, never finishes
    r, events = await run(team_spec(max_delegations=2), endless)
    assert r.result.status == "failed" and "delegation budget" in (r.result.error or "")


def test_member_names_must_be_unique() -> None:
    spec = team_spec(
        members=[{"name": "a", "agent_id": RESEARCHER}, {"name": "a", "agent_id": WRITER}]
    )
    assert any("unique" in p.message for p in validate_structure(spec))


class Flaky(FakeServices):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    async def call_llm(self, *args: Any) -> str:
        if self.failures > 0:
            self.failures -= 1
            raise NodeError("temporarily unavailable")
        return "fine"


def resilient(**node: Any) -> WorkflowSpec:
    return WorkflowSpec.model_validate(
        {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "a", "type": "llm", "config": {"model": "m", "prompt": "p"}, **node},
                {"id": "end", "type": "end", "config": {"output": "[{{ a }}]"}},
            ],
            "edges": [{"source": "start", "target": "a"}, {"source": "a", "target": "end"}],
        }
    )


async def test_retries_then_success() -> None:
    r, events = await run(resilient(retries=2), Flaky(2))
    assert r.result.output == "[fine]"
    assert [e.will_retry for e in events if e.type == "node.failed"] == [True, True]


async def test_retries_exhausted_and_continue_on_error() -> None:
    r, _ = await run(resilient(retries=1), Flaky(5))
    assert r.result.status == "failed"
    r, events = await run(resilient(on_error="continue"), Flaky(5))
    assert (r.result.status, r.result.output) == ("completed", "[]")
    assert [e.continued for e in events if e.type == "node.failed"] == [True]


class Counting(FakeServices):
    def __init__(self) -> None:
        super().__init__()
        self.usage: dict[str, int] = {}

    async def call_llm(self, *args: Any) -> str:
        for k, v in {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}.items():
            self.usage[k] = self.usage.get(k, 0) + v
        return "fine"


async def test_workflow_result_carries_token_usage() -> None:
    r, events = await run(resilient(), Counting())
    assert r.result.usage == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    assert events[-1].usage == r.result.usage
