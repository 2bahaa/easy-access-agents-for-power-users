import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, status
from fastapi.responses import StreamingResponse

from app.api.deps import PrincipalDep, SessionDep, SessionFactoryDep, SettingsDep
from app.api.sse import SSE_HEADERS, follow_run_sse
from app.schemas.runs import AnalyticsSummary, RunEventRead, RunListItem, RunPage, RunRead
from app.services import analytics_service, run_service

router = APIRouter(prefix="/runs", tags=["runs"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
async def list_runs(
    principal: PrincipalDep,
    session: SessionDep,
    kind: Annotated[str | None, Query(pattern="^(agent|workflow)$")] = None,
    status: Annotated[str | None, Query(max_length=32)] = None,
    agent_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunPage:
    """Execution history for the workspace, newest first."""
    rows, total = await analytics_service.list_runs(
        session,
        principal.workspace_id,
        kind=kind,
        status=status,
        agent_id=agent_id,
        workflow_id=workflow_id,
        limit=limit,
        offset=offset,
    )
    items = [
        RunListItem.model_validate(run).model_copy(
            update={"agent_name": agent_name, "workflow_name": workflow_name}
        )
        for run, agent_name, workflow_name in rows
    ]
    return RunPage(items=items, total=total)


@analytics_router.get("/summary")
async def analytics_summary(
    principal: PrincipalDep,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> AnalyticsSummary:
    """Usage, reliability and latency over the last `days`, from recorded runs only."""
    return AnalyticsSummary.model_validate(
        await analytics_service.summary(session, principal.workspace_id, days)
    )


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> RunRead:
    return RunRead.model_validate(
        await run_service.get_run(session, run_id, principal.workspace_id)
    )


@router.get("/{run_id}/events")
async def list_run_events(
    run_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[RunEventRead]:
    events = await run_service.list_run_events(session, run_id, principal.workspace_id)
    return [RunEventRead.model_validate(e) for e in events]


@router.get(
    "/{run_id}/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Run event stream"}},
)
async def stream_run(
    run_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    settings: SettingsDep,
    after: Annotated[int, Query(ge=0, description="Resume after this event seq")] = 0,
    last_event_id: Annotated[int | None, Header(ge=0)] = None,
) -> StreamingResponse:
    """Follow a run (active or finished): replays persisted events after the given seq
    (Last-Event-ID header or ?after=), then streams live events until the run ends."""
    await run_service.get_run(session, run_id, principal.workspace_id)  # 404 before streaming
    after_seq = last_event_id if last_event_id is not None else after
    return StreamingResponse(
        follow_run_sse(session_factory, settings.listen_dsn, run_id, after_seq),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(run_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await run_service.cancel_run(session, principal, run_id)
