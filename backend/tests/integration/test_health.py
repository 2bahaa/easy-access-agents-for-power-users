from httpx import AsyncClient


async def test_health_reports_database_ok(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["database"] == "ok"
    assert body["ollama"] in {"ok", "error"}  # Ollama may not be running in CI
    assert body["status"] == ("ok" if body["ollama"] == "ok" else "degraded")
