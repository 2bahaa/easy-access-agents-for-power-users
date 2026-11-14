import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import SessionDep, SettingsDep
from app.schemas.health import CheckStatus, HealthRead

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: SessionDep, settings: SettingsDep) -> HealthRead:
    database: CheckStatus = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - report, don't crash
        database = "error"

    ollama: CheckStatus = "ok"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            (await client.get(f"{settings.ollama_base_url}/api/version")).raise_for_status()
    except httpx.HTTPError:
        ollama = "error"

    status = "ok" if database == "ok" and ollama == "ok" else "degraded"
    return HealthRead(status=status, database=database, ollama=ollama)
