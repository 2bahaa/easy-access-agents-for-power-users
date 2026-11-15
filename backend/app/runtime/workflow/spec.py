"""The workflow contract: what the visual editor saves and the backend validates and runs.

The frontend's canvas JSON is never trusted: it is parsed into this spec, every node config
is validated by its Pydantic model, and the graph structure is checked (one start, reachable
ends, no cycles, valid branch handles) before anything executes.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict, deque
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

NODE_ID = r"^[a-zA-Z_][a-zA-Z0-9_]{0,39}$"
MAX_NODES = 100
SCHEMA_VERSION: Literal[1] = 1


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputDef(_Config):
    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,39}$")
    description: str = Field(default="", max_length=300)


class StartConfig(_Config):
    inputs: list[InputDef] = Field(default_factory=list, max_length=20)


class EndConfig(_Config):
    output: str = Field(
        default="", max_length=10_000, description="Template of the workflow result"
    )


class AgentNodeConfig(_Config):
    agent_id: uuid.UUID
    prompt: str = Field(min_length=1, max_length=20_000)
    use_draft: bool = False  # default: the agent's latest published version


class LlmNodeConfig(_Config):
    provider: str = Field(default="ollama", max_length=50)
    connection_id: uuid.UUID | None = None
    model: str = Field(min_length=1, max_length=200)
    system: str = Field(default="", max_length=20_000)
    prompt: str = Field(min_length=1, max_length=20_000)
    temperature: float | None = Field(default=None, ge=0, le=2)


class ToolNodeConfig(_Config):
    tool: str = Field(min_length=1, max_length=64)
    args: dict[str, str] = Field(default_factory=dict, max_length=30)  # values are templates
    config: dict[str, Any] = Field(default_factory=dict)


class KnowledgeNodeConfig(_Config):
    collection_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class MemoryNodeConfig(_Config):
    agent_id: uuid.UUID
    action: Literal["save", "search"]
    text: str = Field(min_length=1, max_length=2000)


class ConditionConfig(_Config):
    expression: str = Field(min_length=1, max_length=500)


class RouterConfig(_Config):
    provider: str = Field(default="ollama", max_length=50)
    connection_id: uuid.UUID | None = None
    model: str = Field(min_length=1, max_length=200)
    routes: list[str] = Field(min_length=2, max_length=10)
    instructions: str = Field(default="", max_length=5000)
    input: str = Field(min_length=1, max_length=10_000)


class ParallelConfig(_Config):
    pass


class ApprovalConfig(_Config):
    message: str = Field(min_length=1, max_length=2000)


class TeamMember(_Config):
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,39}$")
    agent_id: uuid.UUID
    role: str = Field(default="", max_length=500, description="What this member is good at")


class SupervisorConfig(_Config):
    """A coordinating model that delegates tasks to member agents and composes the answer."""

    provider: str = Field(default="ollama", max_length=50)
    connection_id: uuid.UUID | None = None
    model: str = Field(min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=5000)
    task: str = Field(min_length=1, max_length=20_000, description="Template of the team's task")
    members: list[TeamMember] = Field(min_length=1, max_length=10)
    max_delegations: int = Field(default=4, ge=1, le=20)
    # Members see only their delegated task unless the original task is shared.
    share_task_with_members: bool = False


CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "start": StartConfig,
    "end": EndConfig,
    "agent": AgentNodeConfig,
    "llm": LlmNodeConfig,
    "tool": ToolNodeConfig,
    "knowledge": KnowledgeNodeConfig,
    "memory": MemoryNodeConfig,
    "condition": ConditionConfig,
    "router": RouterConfig,
    "parallel": ParallelConfig,
    "approval": ApprovalConfig,
    "supervisor": SupervisorConfig,
}
NodeType = Literal[
    "start",
    "end",
    "agent",
    "llm",
    "tool",
    "knowledge",
    "memory",
    "condition",
    "router",
    "parallel",
    "approval",
    "supervisor",
]
BRANCHING = {"condition": {"true", "false"}, "approval": {"approved", "rejected"}}


class Position(BaseModel):
    x: float = 0
    y: float = 0


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=NODE_ID)]
    type: NodeType
    label: str = Field(default="", max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    position: Position = Field(default_factory=Position)  # editor layout only
    # Resilience: retry a failing node, then fail the run or continue with an empty output.
    retries: int = Field(default=0, ge=0, le=3)
    on_error: Literal["fail", "continue"] = "fail"


class EdgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    # Which branch of a condition/router/approval node this edge leaves from.
    source_handle: str | None = Field(default=None, max_length=100)


class WorkflowSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    nodes: list[NodeSpec] = Field(max_length=MAX_NODES)
    edges: list[EdgeSpec] = Field(default_factory=list, max_length=MAX_NODES * 4)


class SpecProblem(BaseModel):
    node_id: str | None = None
    message: str


def parse_config(node: NodeSpec) -> BaseModel:
    return CONFIG_MODELS[node.type].model_validate(node.config)


TEMPLATE_REF = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\.([a-zA-Z_][a-zA-Z0-9_]*))?\s*\}\}")


def template_refs(text: str) -> set[str]:
    """Node ids / `input` referenced by {{ node }} / {{ input.name }} placeholders."""
    return {m.group(1) for m in TEMPLATE_REF.finditer(text)}


def _texts(cfg: BaseModel) -> list[str]:
    out: list[str] = []
    for value in cfg.model_dump().values():
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            out.extend(v for v in value.values() if isinstance(v, str))
    return out


def validate_structure(spec: WorkflowSpec) -> list[SpecProblem]:
    """Graph-level checks that need no database. Returns problems (empty = valid)."""
    problems: list[SpecProblem] = []
    ids = [n.id for n in spec.nodes]
    by_id = {n.id: n for n in spec.nodes}
    if len(set(ids)) != len(ids):
        problems.append(SpecProblem(message="Node ids must be unique"))
    starts = [n for n in spec.nodes if n.type == "start"]
    ends = [n for n in spec.nodes if n.type == "end"]
    if len(starts) != 1:
        problems.append(SpecProblem(message="A workflow needs exactly one Start node"))
    if not ends:
        problems.append(SpecProblem(message="A workflow needs at least one End node"))
    for node in spec.nodes:
        if node.id == "input":
            problems.append(SpecProblem(node_id=node.id, message="'input' is reserved"))
        try:
            parse_config(node)
        except ValidationError as err:
            first = err.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "config"
            problems.append(SpecProblem(node_id=node.id, message=f"{where}: {first['msg']}"))

    out_edges: dict[str, list[EdgeSpec]] = defaultdict(list)
    in_degree: dict[str, int] = defaultdict(int)
    for e in spec.edges:
        if e.source not in by_id or e.target not in by_id:
            problems.append(
                SpecProblem(message=f"Edge {e.source} → {e.target} references a missing node")
            )
            continue
        if by_id[e.target].type == "start":
            problems.append(SpecProblem(node_id=e.target, message="Nothing may connect into Start"))
        if by_id[e.source].type == "end":
            problems.append(
                SpecProblem(node_id=e.source, message="End has no outgoing connections")
            )
        out_edges[e.source].append(e)
        in_degree[e.target] += 1
    if problems:
        return problems

    for node in spec.nodes:
        edges = out_edges[node.id]
        handles = {edge.source_handle for edge in edges}
        if node.type in BRANCHING:
            expected = BRANCHING[node.type]
            if handles != expected:
                problems.append(
                    SpecProblem(
                        node_id=node.id,
                        message=f"Connect both branches: {', '.join(sorted(expected))}",
                    )
                )
        elif node.type == "router":
            routes = set(RouterConfig.model_validate(node.config).routes)
            if not handles or not handles <= routes or None in handles:
                problems.append(
                    SpecProblem(
                        node_id=node.id,
                        message="Each router edge must leave from one of its routes",
                    )
                )
        elif node.type != "end":
            if not edges:
                problems.append(
                    SpecProblem(node_id=node.id, message="This node leads nowhere; connect it")
                )
            elif node.type != "parallel" and len(edges) > 1:
                problems.append(
                    SpecProblem(
                        node_id=node.id, message="Use a Parallel node to fan out to several nodes"
                    )
                )
        if node.type != "start" and in_degree[node.id] == 0:
            problems.append(SpecProblem(node_id=node.id, message="Not connected to the workflow"))
    if problems or not starts:
        return problems

    # Acyclic (Kahn) and every node reachable from Start.
    indeg = dict(in_degree)
    queue = deque(n.id for n in spec.nodes if indeg.get(n.id, 0) == 0)
    seen = 0
    while queue:
        cur = queue.popleft()
        seen += 1
        for edge in out_edges[cur]:
            indeg[edge.target] -= 1
            if indeg[edge.target] == 0:
                queue.append(edge.target)
    if seen != len(spec.nodes):
        problems.append(SpecProblem(message="Workflows cannot contain loops"))
        return problems

    for node in spec.nodes:
        if node.type == "supervisor":
            member_names = [m.name for m in SupervisorConfig.model_validate(node.config).members]
            if len(set(member_names)) != len(member_names):
                problems.append(
                    SpecProblem(node_id=node.id, message="Team member names must be unique")
                )

    # Condition expressions must parse and reference earlier steps / inputs only.
    from app.runtime.workflow.expressions import ExpressionError, condition_names

    ancestors_for_conditions = _ancestors(spec, out_edges)
    start_inputs = {i.name for i in StartConfig.model_validate(starts[0].config).inputs}
    for node in spec.nodes:
        if node.type != "condition":
            continue
        try:
            names = condition_names(ConditionConfig.model_validate(node.config).expression)
        except ExpressionError as e:
            problems.append(SpecProblem(node_id=node.id, message=str(e)))
            continue
        for name in names:
            if name.startswith("input_"):
                if name.removeprefix("input_") not in start_inputs:
                    problems.append(SpecProblem(node_id=node.id, message=f"Unknown input '{name}'"))
            elif name not in ancestors_for_conditions[node.id]:
                problems.append(
                    SpecProblem(node_id=node.id, message=f"'{name}' is not an earlier step")
                )

    # Templates may reference inputs and upstream nodes only.
    ancestors = _ancestors(spec, out_edges)
    inputs = {i.name for i in StartConfig.model_validate(starts[0].config).inputs}
    for node in spec.nodes:
        cfg = parse_config(node)
        refs: set[str] = set()
        for text in _texts(cfg):
            refs |= template_refs(text)
            if node.type == "end" or node.type in (
                "agent",
                "llm",
                "tool",
                "knowledge",
                "memory",
                "router",
                "approval",
                "supervisor",
            ):
                for m in TEMPLATE_REF.finditer(text):
                    if m.group(1) == "input" and m.group(2) and m.group(2) not in inputs:
                        problems.append(
                            SpecProblem(node_id=node.id, message=f"Unknown input '{m.group(2)}'")
                        )
        for ref in refs - {"input"}:
            if ref not in ancestors[node.id]:
                problems.append(
                    SpecProblem(node_id=node.id, message=f"'{ref}' is not an earlier step")
                )
    return problems


def _ancestors(spec: WorkflowSpec, out_edges: dict[str, list[EdgeSpec]]) -> dict[str, set[str]]:
    parents: dict[str, set[str]] = defaultdict(set)
    for src, edges in out_edges.items():
        for edge in edges:
            parents[edge.target].add(src)
    memo: dict[str, set[str]] = {}

    def walk(nid: str) -> set[str]:
        if nid not in memo:
            memo[nid] = set()
            for p in parents[nid]:
                memo[nid] |= {p} | walk(p)
        return memo[nid]

    return {n.id: walk(n.id) for n in spec.nodes}


def node_type_schemas() -> dict[str, dict[str, Any]]:
    """JSON Schemas of node configs (the editor builds its forms from these)."""
    return {name: model.model_json_schema() for name, model in CONFIG_MODELS.items()}


spec_adapter: TypeAdapter[WorkflowSpec] = TypeAdapter(WorkflowSpec)
