import uuid

from fastapi import APIRouter, status

from app.api.deps import RunManagerDep, SessionDep
from app.schemas.runs import RunEventRead, RunRead
from app.services import run_service

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, session: SessionDep) -> RunRead:
    return RunRead.model_validate(await run_service.get_run(session, run_id))


@router.get("/{run_id}/events")
async def list_run_events(run_id: uuid.UUID, session: SessionDep) -> list[RunEventRead]:
    events = await run_service.list_run_events(session, run_id)
    return [RunEventRead.model_validate(e) for e in events]


@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(run_id: uuid.UUID, session: SessionDep, manager: RunManagerDep) -> None:
    await run_service.cancel_run(session, run_id, manager)
