import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, status
from fastapi.responses import StreamingResponse

from app.api.deps import PrincipalDep, SessionDep, SessionFactoryDep, SettingsDep
from app.api.sse import SSE_HEADERS, follow_run_sse
from app.schemas.runs import RunEventRead, RunRead
from app.services import run_service

router = APIRouter(prefix="/runs", tags=["runs"])


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
