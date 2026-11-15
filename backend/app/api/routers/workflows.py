"""Visual workflows: CRUD, validation, versions, runs, node-type schemas and templates."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import PrincipalDep, ProviderResolverDep, SessionDep, SettingsDep, ToolRegistryDep
from app.db.models import Workflow
from app.runtime.workflow.spec import SpecProblem, WorkflowSpec, node_type_schemas
from app.schemas.runs import RunRead
from app.services import workflow_service

router = APIRouter(tags=["workflows"])


class WorkflowWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    spec: WorkflowSpec


class WorkflowSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    node_count: int
    updated_at: datetime


class WorkflowRead(WorkflowSummary):
    spec: dict[str, Any]
    created_at: datetime


class ValidationResult(BaseModel):
    valid: bool
    problems: list[SpecProblem]


class PublishWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(default="", max_length=500)


class VersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    note: str
    created_at: datetime


class StartWorkflowRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: dict[str, str] = Field(default_factory=dict)
    # Run the latest published version instead of the saved draft.
    published: bool = False


class Template(BaseModel):
    id: str
    name: str
    description: str
    spec: WorkflowSpec


def _summary(wf: Workflow) -> WorkflowSummary:
    return WorkflowSummary(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        node_count=len(wf.spec.get("nodes", [])),
        updated_at=wf.updated_at,
    )


def _read(wf: Workflow) -> WorkflowRead:
    return WorkflowRead(**_summary(wf).model_dump(), spec=wf.spec, created_at=wf.created_at)


def _deps(settings: Any, registry: Any, resolver: Any) -> dict[str, Any]:
    return {"settings": settings, "registry": registry, "resolver": resolver}


@router.get("/workflow-node-types")
async def node_types(principal: PrincipalDep) -> dict[str, dict[str, Any]]:
    """JSON Schemas of every node type's configuration (the editor builds forms from them)."""
    return node_type_schemas()


@router.get("/workflow-templates")
async def templates(principal: PrincipalDep) -> list[Template]:
    from app.workflow_templates import TEMPLATES

    return [Template.model_validate(t) for t in TEMPLATES]


@router.post("/workflows/validate")
async def validate(
    data: WorkflowSpec,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
    resolver: ProviderResolverDep,
) -> ValidationResult:
    problems = await workflow_service.validate_spec(
        session, principal, data, **_deps(settings, registry, resolver)
    )
    return ValidationResult(valid=not problems, problems=problems)


@router.get("/workflows")
async def list_workflows(principal: PrincipalDep, session: SessionDep) -> list[WorkflowSummary]:
    return [_summary(w) for w in await workflow_service.list_workflows(session, principal)]


@router.post("/workflows", status_code=status.HTTP_201_CREATED)
async def create_workflow(
    data: WorkflowWrite,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
    resolver: ProviderResolverDep,
) -> WorkflowRead:
    wf = await workflow_service.save_workflow(
        session,
        principal,
        name=data.name,
        description=data.description,
        spec=data.spec,
        **_deps(settings, registry, resolver),
    )
    return _read(wf)


@router.get("/workflows/{workflow_id}")
async def get_workflow(
    workflow_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> WorkflowRead:
    return _read(await workflow_service.get_workflow(session, principal.workspace_id, workflow_id))


@router.put("/workflows/{workflow_id}")
async def update_workflow(
    workflow_id: uuid.UUID,
    data: WorkflowWrite,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
    resolver: ProviderResolverDep,
) -> WorkflowRead:
    wf = await workflow_service.save_workflow(
        session,
        principal,
        name=data.name,
        description=data.description,
        spec=data.spec,
        workflow_id=workflow_id,
        **_deps(settings, registry, resolver),
    )
    return _read(wf)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    await workflow_service.delete_workflow(session, principal, workflow_id)


@router.post("/workflows/{workflow_id}/publish", status_code=status.HTTP_201_CREATED)
async def publish(
    workflow_id: uuid.UUID,
    data: PublishWorkflow,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
    resolver: ProviderResolverDep,
) -> VersionRead:
    v = await workflow_service.publish(
        session, principal, workflow_id, data.note, **_deps(settings, registry, resolver)
    )
    return VersionRead.model_validate(v)


@router.get("/workflows/{workflow_id}/versions")
async def versions(
    workflow_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[VersionRead]:
    return [
        VersionRead.model_validate(v)
        for v in await workflow_service.list_versions(session, principal, workflow_id)
    ]


@router.post("/workflows/{workflow_id}/versions/{version}/restore")
async def restore(
    workflow_id: uuid.UUID, version: int, principal: PrincipalDep, session: SessionDep
) -> WorkflowRead:
    return _read(await workflow_service.restore_version(session, principal, workflow_id, version))


@router.post("/workflows/{workflow_id}/runs", status_code=status.HTTP_201_CREATED)
async def start_run(
    workflow_id: uuid.UUID,
    data: StartWorkflowRun,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    registry: ToolRegistryDep,
    resolver: ProviderResolverDep,
) -> RunRead:
    """Queue a run; follow it with GET /runs/{id}/stream (node.* events)."""
    run = await workflow_service.start_run(
        session,
        principal,
        workflow_id,
        data.inputs,
        published=data.published,
        **_deps(settings, registry, resolver),
    )
    return RunRead.model_validate(run)


@router.get("/workflows/{workflow_id}/runs")
async def list_runs(
    workflow_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[RunRead]:
    return [
        RunRead.model_validate(r)
        for r in await workflow_service.list_runs(session, principal, workflow_id)
    ]
