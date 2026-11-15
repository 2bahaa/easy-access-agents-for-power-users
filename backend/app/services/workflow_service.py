"""Workflows: CRUD, validation (structure + workspace references), versions, runs, and the
`WorkflowServices` implementation the engine uses to reach agents, models, tools,
knowledge and memory (every call goes through the same checks as elsewhere)."""

import uuid
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Agent, KnowledgeCollection, Run, Workflow, WorkflowVersion
from app.runtime.limits import effective_limits
from app.runtime.tool_node import ToolCallError, ToolNode
from app.runtime.types import AgentConfig, RuntimeCaps, ToolGrant
from app.runtime.workflow.engine import NodeError, WorkflowResult, WorkflowResume, WorkflowRun
from app.runtime.workflow.spec import (
    AgentNodeConfig,
    KnowledgeNodeConfig,
    LlmNodeConfig,
    MemoryNodeConfig,
    RouterConfig,
    SpecProblem,
    StartConfig,
    ToolNodeConfig,
    WorkflowSpec,
    parse_config,
    validate_structure,
)
from app.services import (
    agent_platform,
    approval_service,
    audit_service,
    capability_service,
    knowledge_service,
    run_queue,
    run_service,
)
from app.services.errors import ConflictError, DomainValidationError, NotFoundError
from app.services.principal import Principal
from app.services.provider_service import ProviderResolver
from app.services.run_stream import SessionFactory
from app.tools.base import ToolContext
from app.tools.external import is_data_tool, is_external
from app.tools.registry import ToolConfigError, ToolRegistry, UnknownToolError

APPROVAL_TOOL = "workflow.approval"


# ---- validation ---------------------------------------------------------------------------


async def validate_spec(
    session: AsyncSession,
    principal: Principal,
    spec: WorkflowSpec,
    *,
    settings: Settings,
    registry: ToolRegistry,
    resolver: ProviderResolver,
) -> list[SpecProblem]:
    problems = validate_structure(spec)
    if problems:
        return problems
    ws = principal.workspace_id
    agent_ids = set(await session.scalars(select(Agent.id).where(Agent.workspace_id == ws)))
    collection_ids = set(
        await session.scalars(
            select(KnowledgeCollection.id).where(KnowledgeCollection.workspace_id == ws)
        )
    )
    external = {
        t.name
        for t in await capability_service.external_tools(session, ws, settings, resolver.secrets)
    }
    for node in spec.nodes:
        cfg = parse_config(node)
        if isinstance(cfg, (AgentNodeConfig, MemoryNodeConfig)) and cfg.agent_id not in agent_ids:
            problems.append(SpecProblem(node_id=node.id, message="Unknown agent"))
        elif isinstance(cfg, KnowledgeNodeConfig):
            if any(c not in collection_ids for c in cfg.collection_ids):
                problems.append(
                    SpecProblem(node_id=node.id, message="Unknown knowledge collection")
                )
        elif isinstance(cfg, ToolNodeConfig):
            if is_data_tool(cfg.tool):
                problems.append(
                    SpecProblem(node_id=node.id, message="Use a Knowledge or Memory node instead")
                )
            elif is_external(cfg.tool):
                if cfg.tool not in external:
                    problems.append(
                        SpecProblem(
                            node_id=node.id, message=f"Tool '{cfg.tool}' is unknown or disabled"
                        )
                    )
            else:
                try:
                    registry.normalize_config(cfg.tool, cfg.config)
                except UnknownToolError:
                    problems.append(
                        SpecProblem(node_id=node.id, message=f"Unknown tool '{cfg.tool}'")
                    )
                except ToolConfigError as e:
                    problems.append(SpecProblem(node_id=node.id, message=str(e)))
        elif isinstance(cfg, (LlmNodeConfig, RouterConfig)):
            try:
                await resolver.resolve(session, ws, cfg.provider, cfg.connection_id)
            except (DomainValidationError, NotFoundError):
                problems.append(SpecProblem(node_id=node.id, message="Unknown model provider"))
    return problems


async def _require_valid(
    session: AsyncSession, principal: Principal, spec: WorkflowSpec, **deps: Any
) -> None:
    problems = await validate_spec(session, principal, spec, **deps)
    if problems:
        first = problems[0]
        where = f"{first.node_id}: " if first.node_id else ""
        raise DomainValidationError(f"Invalid workflow — {where}{first.message}")


# ---- CRUD & versions ------------------------------------------------------------------------


async def get_workflow(
    session: AsyncSession, workspace_id: uuid.UUID, workflow_id: uuid.UUID
) -> Workflow:
    wf = await session.get(Workflow, workflow_id, populate_existing=True)
    if wf is None or wf.workspace_id != workspace_id:
        raise NotFoundError(f"Workflow {workflow_id} not found")
    return wf


async def list_workflows(session: AsyncSession, principal: Principal) -> Sequence[Workflow]:
    stmt = select(Workflow).where(Workflow.workspace_id == principal.workspace_id)
    return (await session.scalars(stmt.order_by(Workflow.updated_at.desc()))).all()


async def save_workflow(
    session: AsyncSession,
    principal: Principal,
    *,
    name: str,
    description: str,
    spec: WorkflowSpec,
    workflow_id: uuid.UUID | None = None,
    strict: bool = False,
    **deps: Any,
) -> Workflow:
    """Drafts may be incomplete (saved while editing); `strict` requires a valid spec."""
    principal.require("editor")
    problems = validate_structure(spec)
    if strict:
        await _require_valid(session, principal, spec, **deps)
    elif any(p.message.startswith(("Node ids", "'input'")) for p in problems):
        raise DomainValidationError(problems[0].message)
    if workflow_id is None:
        wf = Workflow(
            workspace_id=principal.workspace_id,
            created_by=principal.user_id,
            name=name,
            description=description,
            spec={},
        )
        session.add(wf)
    else:
        wf = await get_workflow(session, principal.workspace_id, workflow_id)
        wf.updated_at = func.now()
    wf.name, wf.description, wf.spec = name, description, spec.model_dump(mode="json")
    await session.commit()
    return await get_workflow(session, principal.workspace_id, wf.id)


async def delete_workflow(
    session: AsyncSession, principal: Principal, workflow_id: uuid.UUID
) -> None:
    principal.require("editor")
    wf = await get_workflow(session, principal.workspace_id, workflow_id)
    await session.delete(wf)
    audit_service.record(
        session,
        "workflow.deleted",
        principal=principal,
        target_type="workflow",
        target_id=workflow_id,
    )
    await session.commit()


async def publish(
    session: AsyncSession, principal: Principal, workflow_id: uuid.UUID, note: str, **deps: Any
) -> WorkflowVersion:
    principal.require("editor")
    wf = await get_workflow(session, principal.workspace_id, workflow_id)
    await _require_valid(session, principal, WorkflowSpec.model_validate(wf.spec), **deps)
    current = await session.scalar(
        select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_id == wf.id)
    )
    version = WorkflowVersion(
        workflow_id=wf.id,
        version=(current or 0) + 1,
        spec=wf.spec,
        note=note,
        created_by=principal.user_id,
    )
    session.add(version)
    audit_service.record(
        session,
        "workflow.published",
        principal=principal,
        target_type="workflow",
        target_id=wf.id,
        version=version.version,
    )
    await session.commit()
    return version


async def list_versions(
    session: AsyncSession, principal: Principal, workflow_id: uuid.UUID
) -> Sequence[WorkflowVersion]:
    await get_workflow(session, principal.workspace_id, workflow_id)
    stmt = select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id)
    return (await session.scalars(stmt.order_by(WorkflowVersion.version.desc()))).all()


async def restore_version(
    session: AsyncSession, principal: Principal, workflow_id: uuid.UUID, version: int
) -> Workflow:
    principal.require("editor")
    wf = await get_workflow(session, principal.workspace_id, workflow_id)
    row = await session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == wf.id, WorkflowVersion.version == version
        )
    )
    if row is None:
        raise NotFoundError(f"Version {version} not found")
    wf.spec, wf.updated_at = row.spec, func.now()
    await session.commit()
    return await get_workflow(session, principal.workspace_id, workflow_id)


# ---- runs -----------------------------------------------------------------------------------


async def start_run(
    session: AsyncSession,
    principal: Principal,
    workflow_id: uuid.UUID,
    inputs: dict[str, str],
    *,
    published: bool = False,
    **deps: Any,
) -> Run:
    principal.require("editor")
    wf = await get_workflow(session, principal.workspace_id, workflow_id)
    spec_json = wf.spec
    if published:
        latest = await session.scalar(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == wf.id)
            .order_by(WorkflowVersion.version.desc())
            .limit(1)
        )
        if latest is None:
            raise ConflictError("This workflow has not been published yet")
        spec_json = latest.spec
    spec = WorkflowSpec.model_validate(spec_json)
    await _require_valid(session, principal, spec, **deps)
    start = next(n for n in spec.nodes if n.type == "start")
    declared = [i.name for i in StartConfig.model_validate(start.config).inputs]
    missing = [n for n in declared if not str(inputs.get(n, "")).strip()]
    if missing:
        raise DomainValidationError(f"Missing input(s): {', '.join(missing)}")
    run = Run(
        workspace_id=principal.workspace_id,
        kind="workflow",
        workflow_id=wf.id,
        status="queued",
        agent_snapshot=spec.model_dump(mode="json"),
        inputs={k: str(inputs.get(k, ""))[:20_000] for k in declared},
    )
    session.add(run)
    await session.flush()
    await run_queue.wake_workers(session)
    await session.commit()
    return run


async def list_runs(
    session: AsyncSession, principal: Principal, workflow_id: uuid.UUID
) -> Sequence[Run]:
    await get_workflow(session, principal.workspace_id, workflow_id)
    stmt = (
        select(Run).where(Run.workflow_id == workflow_id).order_by(Run.started_at.desc()).limit(50)
    )
    return (await session.scalars(stmt)).all()


async def apply_result(
    session: AsyncSession, run: Run, result: WorkflowResult, approval_ttl_s: float
) -> None:
    """Persist a finished/paused workflow run (caller commits with the terminal event)."""
    run.output = result.output or None
    run.state = {"outputs": result.outputs}
    run.tool_call_count = result.executed
    run.error = result.error
    run.finished_at = func.now()
    if result.status == "waiting_approval" and result.pending:
        run.status = "waiting_approval"
        approval_service.create_requests(
            session,
            run,
            [
                {
                    "call_id": result.pending["node_id"],
                    "tool": APPROVAL_TOOL,
                    "args": {"message": result.pending["message"]},
                }
            ],
            approval_ttl_s,
        )
    else:
        run.status = result.status if result.status != "running" else "failed"


class DbWorkflowServices:
    """What workflow nodes may do, bound to one workspace and run."""

    def __init__(
        self,
        session_factory: SessionFactory,
        settings: Settings,
        resolver: ProviderResolver,
        tools: ToolRegistry,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.resolver = resolver
        self.tools = tools
        self.workspace_id = workspace_id
        self.run_id = run_id

    async def run_agent(self, agent_id: uuid.UUID, prompt: str, use_draft: bool) -> str:
        from app.services.agent_service import get_agent

        async with self.session_factory() as session:
            try:
                agent = await get_agent(session, agent_id, self.workspace_id)
            except NotFoundError:
                raise NodeError("The agent of this step no longer exists") from None
            config, _version = await agent_platform.runtime_config_for_chat(
                session, agent, playground=use_draft
            )
            config = await approval_service.apply_policies(
                session, self.workspace_id, agent.id, config
            )
            agent_run = await run_service.build_agent_run(
                session,
                run_id=uuid.uuid4(),
                workspace_id=self.workspace_id,
                agent_id=agent.id,
                config=config,
                history=[HumanMessage(prompt)],
                settings=self.settings,
                resolver=self.resolver,
                tools=self.tools,
                session_factory=self.session_factory,
            )
        async for _event in agent_run.stream():
            pass  # node-level events only; the agent's own steps are not re-streamed
        result = agent_run.result
        if result.status == "waiting_approval":
            raise NodeError(
                "This agent needs tool approval; use an Approval node in workflows instead"
            )
        if result.status != "completed":
            raise NodeError(result.error or f"The agent run ended with status {result.status}")
        final = next(
            (m for m in reversed(result.new_messages) if isinstance(m, AIMessage) and m.text), None
        )
        return final.text if final else ""

    async def call_llm(
        self,
        provider: str,
        connection_id: uuid.UUID | None,
        model: str,
        system: str,
        prompt: str,
        temperature: float | None,
    ) -> str:
        async with self.session_factory() as session:
            p = await self.resolver.resolve(session, self.workspace_id, provider, connection_id)
        params = {"temperature": temperature} if temperature is not None else {}
        chat = p.create_chat_model(model, params)
        messages = ([SystemMessage(system)] if system.strip() else []) + [HumanMessage(prompt)]
        try:
            reply = await chat.ainvoke(messages)
        except Exception as e:
            if p.is_provider_error(e):
                raise NodeError(f"Model provider error: {str(e)[:200]}") from None
            raise
        return str(reply.text)

    async def run_tool(self, tool: str, args: dict[str, Any], config: dict[str, Any]) -> str:
        async with self.session_factory() as session:
            registry = self.tools
            if is_external(tool):
                registry = registry.extended(
                    await capability_service.external_tools(
                        session,
                        self.workspace_id,
                        self.settings,
                        self.resolver.secrets,
                        names=[tool],
                    )
                )
                normalized: dict[str, Any] = {}
            else:
                try:
                    normalized = registry.normalize_config(tool, config)
                except (UnknownToolError, ToolConfigError) as e:
                    raise NodeError(str(e)) from None
            from app.db.models import Workspace

            workspace = await session.get(Workspace, self.workspace_id)
            assert workspace is not None
        caps = RuntimeCaps(
            max_tool_calls=self.settings.max_tool_calls_cap,
            run_timeout_s=self.settings.run_timeout_cap_s,
            tool_timeout_s=self.settings.tool_timeout_s,
        )
        dummy = AgentConfig(agent_id=uuid.uuid4(), name="workflow", provider="none", model="none")
        node = ToolNode(
            registry,
            [ToolGrant(name=tool, config=normalized)],
            effective_limits(dummy, caps),
            ToolContext(workspace_dir=run_service.workspace_files_dir(self.settings, workspace)),
        )
        try:
            return await node.run_single(tool, args)
        except ToolCallError as e:
            raise NodeError(f"Tool '{tool}' failed ({e.kind}): {e.message}") from None

    async def search_knowledge(
        self, collection_ids: list[uuid.UUID], query: str, top_k: int
    ) -> str:
        async with self.session_factory() as session:
            try:
                hits = await knowledge_service.search(
                    session,
                    self.resolver,
                    self.settings,
                    self.workspace_id,
                    collection_ids,
                    query,
                    top_k,
                )
            except NotFoundError:
                raise NodeError("A knowledge collection of this step no longer exists") from None
        return knowledge_service.format_hits(hits)

    async def memory(self, agent_id: uuid.UUID, action: str, text: str) -> str:
        from app.services.agent_service import get_agent

        async with self.session_factory() as session:
            try:
                await get_agent(session, agent_id, self.workspace_id)
            except NotFoundError:
                raise NodeError("The agent of this memory step no longer exists") from None
            if action == "save":
                await knowledge_service.save_memory(
                    session, self.workspace_id, agent_id, text, None
                )
                return "Saved to memory."
            found = await knowledge_service.search_memories(
                session, self.workspace_id, agent_id, text
            )
        return "\n".join(f"- {m.content}" for m in found) or "No memories."


async def prepare_workflow_run(
    session: AsyncSession,
    run: Run,
    *,
    settings: Settings,
    resolver: ProviderResolver,
    tools: ToolRegistry,
    session_factory: SessionFactory,
) -> WorkflowRun:
    spec = WorkflowSpec.model_validate(run.agent_snapshot)
    resume = None
    if run.resume_of is not None:
        original = await session.get(Run, run.resume_of)
        decisions = await approval_service.decisions_for(session, run.resume_of)
        node_id = next(iter([*decisions.approved, *decisions.rejected]), None)
        if original is not None and node_id is not None:
            resume = WorkflowResume(
                node_id=node_id,
                approved=node_id in decisions.approved,
                outputs=dict((original.state or {}).get("outputs") or {}),
                note=decisions.rejected.get(node_id, ""),
            )
    services = DbWorkflowServices(
        session_factory, settings, resolver, tools, run.workspace_id, run.id
    )
    return WorkflowRun(
        run.id,
        spec,
        {k: str(v) for k, v in (run.inputs or {}).items()},
        services,
        workflow_id=run.workflow_id,
        timeout_s=float(settings.workflow_timeout_s),
        resume=resume,
    )
