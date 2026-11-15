"""Execute a validated WorkflowSpec as a LangGraph StateGraph.

    run = WorkflowRun(run_id, spec, inputs, services, timeout_s=300)
    async for event in run.stream(): ...      # node.* events, one terminal run.* event
    run.result                                 # status, output, outputs, pending approval

* Each spec node becomes a graph node; Parallel fans out with plain edges and nodes with
  several incoming edges are `defer`red so they run once, after all active branches.
* Condition / router / approval nodes route with conditional edges on their output.
* An approval node pauses the workflow (status `waiting_approval`); a continuation run
  resumes from that node with the stored outputs and the human decision.
* The engine never touches the database: agents, models, tools, knowledge and memory are
  provided by `WorkflowServices`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import operator
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Protocol, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from app.runtime.events import AgentEvent, agent_event_adapter
from app.runtime.workflow.expressions import ExpressionError, evaluate, render
from app.runtime.workflow.spec import (
    AgentNodeConfig,
    ApprovalConfig,
    ConditionConfig,
    EndConfig,
    KnowledgeNodeConfig,
    LlmNodeConfig,
    MemoryNodeConfig,
    NodeSpec,
    RouterConfig,
    SupervisorConfig,
    ToolNodeConfig,
    WorkflowSpec,
    parse_config,
)

logger = logging.getLogger(__name__)
PREVIEW = 2_000
PAUSE = "__pause__"
OUTPUT_KEY = "__output__"


class NodeError(Exception):
    """User-safe failure of a node (shown in events)."""


class WorkflowServices(Protocol):
    async def run_agent(self, agent_id: uuid.UUID, prompt: str, use_draft: bool) -> str: ...

    async def call_llm(
        self,
        provider: str,
        connection_id: uuid.UUID | None,
        model: str,
        system: str,
        prompt: str,
        temperature: float | None,
    ) -> str: ...

    async def run_tool(self, tool: str, args: dict[str, Any], config: dict[str, Any]) -> str: ...

    async def search_knowledge(
        self, collection_ids: list[uuid.UUID], query: str, top_k: int
    ) -> str: ...

    async def memory(self, agent_id: uuid.UUID, action: str, text: str) -> str: ...

    async def chat(
        self,
        provider: str,
        connection_id: uuid.UUID | None,
        model: str,
        messages: list[BaseMessage],
        tools: list[dict[str, Any]],
    ) -> AIMessage: ...


@dataclass(frozen=True)
class WorkflowResume:
    """Continue after an approval node: the stored outputs and the decision for that node."""

    node_id: str
    approved: bool
    outputs: dict[str, str]
    note: str = ""


@dataclass
class WorkflowResult:
    status: str = "running"  # completed | failed | cancelled | timeout | waiting_approval
    output: str = ""
    outputs: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    executed: int = 0
    pending: dict[str, str] | None = None  # {"node_id", "message"} when paused
    # Provider-reported tokens of every model call made by the run's nodes.
    usage: dict[str, int] = field(default_factory=dict)


def _merge(a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    return {**a, **b}


class State(TypedDict, total=False):
    outputs: Annotated[dict[str, str], _merge]
    path: Annotated[list[str], operator.add]
    paused: Annotated[list[str], operator.add]


def _preview(text: str) -> str:
    return (
        text if len(text) <= PREVIEW else text[:PREVIEW] + f"… [{len(text) - PREVIEW} more chars]"
    )


class WorkflowRun:
    def __init__(
        self,
        run_id: uuid.UUID,
        spec: WorkflowSpec,
        inputs: dict[str, str],
        services: WorkflowServices,
        *,
        workflow_id: uuid.UUID | None = None,
        timeout_s: float = 300.0,
        resume: WorkflowResume | None = None,
    ) -> None:
        self.run_id = run_id
        self.spec = spec
        self.inputs = inputs
        self.services = services
        self.workflow_id = workflow_id
        self.timeout_s = timeout_s
        self.resume = resume
        self.result = WorkflowResult()
        self._queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        self._seq = 0
        self._task: asyncio.Task[None] | None = None
        self._started = time.perf_counter()
        self._nodes = {n.id: n for n in spec.nodes}

    # ---- public ------------------------------------------------------------------------

    async def stream(self) -> AsyncIterator[AgentEvent]:
        if self._task is not None:
            raise RuntimeError("WorkflowRun.stream() can only be consumed once")
        self._task = asyncio.create_task(self._produce())
        try:
            while (event := await self._queue.get()) is not None:
                yield event
            await self._task
        finally:
            if not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

    def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()

    # ---- internals ---------------------------------------------------------------------

    def _emit(self, event_type: str, **payload: Any) -> None:
        if event_type.startswith("run.") and event_type != "run.started":
            self.usage()  # terminal: the result carries the tokens spent so far
        self._seq += 1
        self._queue.put_nowait(
            agent_event_adapter.validate_python(
                {"type": event_type, "run_id": self.run_id, "seq": self._seq, **payload}
            )
        )

    def _ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)

    async def _produce(self) -> None:
        self._emit("run.started", workflow_id=self.workflow_id, model=None, agent_id=None)
        try:
            async with asyncio.timeout(self.timeout_s):
                await self._execute()
        except NodeError as e:
            self.result.status, self.result.error = "failed", str(e)
            self._emit("run.failed", code="node_failed", message=str(e))
        except TimeoutError:
            self.result.status = "timeout"
            self.result.error = f"Workflow exceeded {self.timeout_s:g}s"
            self._emit("run.failed", code="timeout", message=self.result.error)
        except asyncio.CancelledError:
            self.result.status = "cancelled"
            self._emit("run.cancelled")
        except Exception:
            logger.exception("Workflow run %s failed", self.run_id)
            self.result.status, self.result.error = (
                "failed",
                "Internal error while running the workflow",
            )
            self._emit("run.failed", code="internal_error", message=self.result.error)
        finally:
            self._queue.put_nowait(None)

    async def _execute(self) -> None:
        graph = self._compile()
        state: State = {
            "outputs": dict(self.resume.outputs) if self.resume else {},
            "path": [],
            "paused": [],
        }
        final: dict[str, Any] = dict(state)
        async for chunk in graph.astream(
            state, stream_mode="values", config={"recursion_limit": len(self._nodes) * 3 + 10}
        ):
            final = chunk
        outputs = dict(final.get("outputs") or {})
        self.result.outputs = {k: v for k, v in outputs.items() if not k.startswith("__")}
        paused = final.get("paused") or []
        if paused:
            node = self._nodes[paused[0]]
            message = render(
                ApprovalConfig.model_validate(node.config).message, outputs, self.inputs
            )
            self.result.status = "waiting_approval"
            self.result.pending = {"node_id": node.id, "message": message}
            self._emit(
                "approval.requested",
                call_id=node.id,
                tool="workflow.approval",
                args={"message": message},
            )
            self._emit("run.waiting_approval", pending=[node.id])
            return
        self.result.status = "completed"
        self.result.output = outputs.get(OUTPUT_KEY, "")
        self._emit(
            "run.completed",
            tool_call_count=self.result.executed,
            usage=self.usage(),
            duration_ms=self._ms(),
            output=self.result.output,
        )

    def usage(self) -> dict[str, int]:
        """Token usage the services recorded (services without a `usage` dict report none)."""
        self.result.usage = dict(getattr(self.services, "usage", None) or {})
        return self.result.usage

    # ---- graph construction --------------------------------------------------------------

    def _compile(self) -> Any:
        out_edges: dict[str, list[Any]] = defaultdict(list)
        in_degree: dict[str, int] = defaultdict(int)
        for e in self.spec.edges:
            out_edges[e.source].append(e)
            in_degree[e.target] += 1
        # LangGraph's overloads are stricter than our dynamic node callables; typed as Any.
        graph: Any = StateGraph(State)
        for node in self.spec.nodes:
            graph.add_node(node.id, self._node_fn(node), defer=in_degree[node.id] > 1)

        start = next(n for n in self.spec.nodes if n.type == "start")
        entry = self.resume.node_id if self.resume else start.id
        graph.add_edge(START, entry)
        for node in self.spec.nodes:
            edges = out_edges[node.id]
            if node.type == "end":
                graph.add_edge(node.id, END)
            elif node.type in ("condition", "router", "approval"):
                mapping = {e.source_handle: e.target for e in edges}
                mapping[PAUSE] = END
                graph.add_conditional_edges(node.id, self._router_fn(node), mapping)
            else:
                for e in edges:
                    graph.add_edge(node.id, e.target)
        return graph.compile()

    def _router_fn(self, node: NodeSpec) -> Callable[[State], str]:
        def route(state: State) -> str:
            if node.id in (state.get("paused") or []):
                return PAUSE
            return (state.get("outputs") or {}).get(f"__route_{node.id}", PAUSE)

        return route

    def _node_fn(self, node: NodeSpec) -> Callable[[State], Any]:
        async def run(state: State) -> dict[str, Any]:
            outputs = dict(state.get("outputs") or {})
            self._emit("node.started", node_id=node.id, node_type=node.type, label=node.label)
            began = time.perf_counter()
            attempt = 0
            while True:
                try:
                    value, extra = await self._run_node(node, outputs)
                    break
                except (NodeError, ExpressionError) as e:
                    message = (
                        str(e) if isinstance(e, NodeError) else f"{node.label or node.id}: {e}"
                    )
                    retry = attempt < node.retries
                    proceed = not retry and node.on_error == "continue"
                    self._emit(
                        "node.failed",
                        node_id=node.id,
                        error=message,
                        will_retry=retry,
                        continued=proceed,
                    )
                    if retry:
                        attempt += 1
                        await asyncio.sleep(min(0.5 * attempt, 2.0))
                        continue
                    if proceed:
                        value, extra = "", {}
                        break
                    raise NodeError(message) from None
            if extra.get("paused"):
                return {"paused": [node.id], "path": [node.id]}
            self.result.executed += 1
            self._emit(
                "node.completed",
                node_id=node.id,
                output=_preview(value),
                duration_ms=int((time.perf_counter() - began) * 1000),
            )
            return {"outputs": {node.id: value, **extra.get("outputs", {})}, "path": [node.id]}

        return run

    async def _run_node(
        self, node: NodeSpec, outputs: dict[str, str]
    ) -> tuple[str, dict[str, Any]]:
        cfg = parse_config(node)

        def t(text: str) -> str:
            return render(text, outputs, self.inputs)

        s = self.services
        try:
            if node.type == "start":
                return "\n".join(f"{k}: {v}" for k, v in self.inputs.items()), {}
            if node.type == "end":
                assert isinstance(cfg, EndConfig)
                rendered = t(cfg.output)
                return rendered, {"outputs": {OUTPUT_KEY: rendered}}
            if node.type == "agent":
                assert isinstance(cfg, AgentNodeConfig)
                return await s.run_agent(cfg.agent_id, t(cfg.prompt), cfg.use_draft), {}
            if node.type == "llm":
                assert isinstance(cfg, LlmNodeConfig)
                text = await s.call_llm(
                    cfg.provider,
                    cfg.connection_id,
                    cfg.model,
                    t(cfg.system),
                    t(cfg.prompt),
                    cfg.temperature,
                )
                return text, {}
            if node.type == "tool":
                assert isinstance(cfg, ToolNodeConfig)
                args: dict[str, Any] = {k: t(v) for k, v in cfg.args.items()}
                return await s.run_tool(cfg.tool, args, cfg.config), {}
            if node.type == "knowledge":
                assert isinstance(cfg, KnowledgeNodeConfig)
                return await s.search_knowledge(cfg.collection_ids, t(cfg.query), cfg.top_k), {}
            if node.type == "memory":
                assert isinstance(cfg, MemoryNodeConfig)
                return await s.memory(cfg.agent_id, cfg.action, t(cfg.text)), {}
            if node.type == "condition":
                assert isinstance(cfg, ConditionConfig)
                branch = "true" if evaluate(cfg.expression, outputs, self.inputs) else "false"
                return branch, {"outputs": {f"__route_{node.id}": branch}}
            if node.type == "router":
                assert isinstance(cfg, RouterConfig)
                label = await self._classify(cfg, t(cfg.input))
                return label, {"outputs": {f"__route_{node.id}": label}}
            if node.type == "approval":
                if self.resume and self.resume.node_id == node.id:
                    branch = "approved" if self.resume.approved else "rejected"
                    note = f" ({self.resume.note})" if self.resume.note else ""
                    return branch + note, {"outputs": {f"__route_{node.id}": branch}}
                return "", {"paused": True}
            if node.type == "parallel":
                return "", {}
            if node.type == "supervisor":
                assert isinstance(cfg, SupervisorConfig)
                return await self._supervise(node, cfg, t(cfg.task)), {}
        except NodeError:
            raise
        except ExpressionError:
            raise
        except Exception as e:  # services raise user-safe errors; anything else is summarised
            logger.warning("Workflow node %s failed: %s", node.id, e)
            raise NodeError(f"{node.label or node.id} failed: {str(e)[:300]}") from None
        raise NodeError(f"Unknown node type {node.type}")  # pragma: no cover

    async def _supervise(self, node: NodeSpec, cfg: SupervisorConfig, task: str) -> str:
        """Supervisor loop: the model delegates to members (bounded) and then finishes."""
        members = {m.name: m for m in cfg.members}
        roster = "\n".join(f"- {m.name}: {m.role or 'general assistant'}" for m in cfg.members)
        system = (
            f"{cfg.instructions}\n\nYou coordinate a team. Members:\n{roster}\n\n"
            "Call `delegate` to give one member a self-contained task (say briefly why), read the "
            f"result, and call `finish` with the final answer. At most {cfg.max_delegations} "
            "delegations."
        ).strip()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "delegate",
                    "description": "Give a team member a task.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "member": {"type": "string", "enum": list(members)},
                            "task": {"type": "string"},
                            "reason": {
                                "type": "string",
                                "description": "One short sentence: why this member",
                            },
                        },
                        "required": ["member", "task"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "finish",
                    "description": "Return the team's final answer.",
                    "parameters": {
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                    },
                },
            },
        ]
        messages: list[BaseMessage] = [SystemMessage(system), HumanMessage(task)]
        delegations = 0
        for _ in range(cfg.max_delegations * 2 + 2):  # rejected calls also use turns
            reply = await self.services.chat(
                cfg.provider, cfg.connection_id, cfg.model, messages, tools
            )
            messages.append(reply)
            if not reply.tool_calls:
                return str(reply.text)  # answered directly
            for call in reply.tool_calls:
                args = call.get("args") or {}
                call_id = call.get("id") or uuid.uuid4().hex
                if call["name"] == "finish":
                    return str(args.get("answer", ""))
                if call["name"] != "delegate":
                    messages.append(
                        ToolMessage(f"Error: unknown tool {call['name']}", tool_call_id=call_id)
                    )
                    continue
                member = members.get(str(args.get("member", "")))
                if member is None:
                    messages.append(
                        ToolMessage(
                            f"Error: no member named {args.get('member')!r}", tool_call_id=call_id
                        )
                    )
                    continue
                if delegations >= cfg.max_delegations:
                    messages.append(
                        ToolMessage(
                            "Error: delegation limit reached; call finish now.",
                            tool_call_id=call_id,
                        )
                    )
                    continue
                delegations += 1
                member_task = str(args.get("task", ""))[:10_000]
                if cfg.share_task_with_members:
                    member_task = f"Overall goal: {task}\n\nYour task: {member_task}"
                self._emit(
                    "agent.delegated",
                    node_id=node.id,
                    member=member.name,
                    agent_id=member.agent_id,
                    task=member_task[:PREVIEW],
                    reason=str(args.get("reason", ""))[:300],
                )
                began = time.perf_counter()
                try:
                    result = await self.services.run_agent(member.agent_id, member_task, False)
                    ok = True
                except NodeError as e:  # a failing member is reported to the supervisor, not fatal
                    result, ok = f"Error: {e}", False
                self._emit(
                    "agent.result",
                    node_id=node.id,
                    member=member.name,
                    output=_preview(result),
                    duration_ms=int((time.perf_counter() - began) * 1000),
                    ok=ok,
                )
                messages.append(ToolMessage(result, tool_call_id=call_id))
        raise NodeError("The supervisor did not finish within its delegation budget")

    async def _classify(self, cfg: RouterConfig, text: str) -> str:
        routes = ", ".join(cfg.routes)
        system = (
            f"{cfg.instructions}\n\nClassify the input into exactly one of these labels: {routes}. "
            "Answer with the label only."
        ).strip()
        answer = (
            (
                await self.services.call_llm(
                    cfg.provider, cfg.connection_id, cfg.model, system, text, 0
                )
            )
            .strip()
            .lower()
        )
        for route in cfg.routes:
            if answer == route.lower():
                return route
        for route in cfg.routes:
            if route.lower() in answer:
                return route
        raise NodeError(f"The router answered '{answer[:60]}', which is not one of: {routes}")
