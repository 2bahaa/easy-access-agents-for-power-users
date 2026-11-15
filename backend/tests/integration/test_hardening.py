"""Production hardening: size limits, security headers, run rate limit, unsafe-config guard."""

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr

from app.api.ratelimit import SlidingWindowLimiter
from app.config import Settings
from app.main import create_app
from tests.fakes import FakeProvider, reply
from tests.sse_helpers import create_agent, create_conversation


async def test_security_headers(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"


async def test_oversized_bodies_are_rejected(client: AsyncClient) -> None:
    big = "x" * 1_100_000
    resp = await client.post("/api/agents", json={"name": "A", "model": "m", "system_prompt": big})
    assert resp.status_code == 413
    assert resp.headers["content-type"] == "application/problem+json"

    async def chunks():  # type: ignore[no-untyped-def]  # no Content-Length: counted while streaming
        for _ in range(12):
            yield b"x" * 100_000

    resp = await client.post(
        "/api/agents", content=chunks(), headers={"content-type": "application/json"}
    )
    assert resp.status_code == 413

    # Knowledge uploads have their own (larger) limit.
    coll = (
        await client.post(
            "/api/knowledge/collections", json={"name": "Docs", "embedding_model": "fake-embed"}
        )
    ).json()
    resp = await client.post(
        f"/api/knowledge/collections/{coll['id']}/documents",
        files={"file": ("big.txt", b"word " * 300_000, "text/plain")},
    )
    assert resp.status_code != 413, resp.text


async def test_run_rate_limit_per_user(
    app: FastAPI, client: AsyncClient, fake_provider: FakeProvider
) -> None:
    app.state.run_limiter = SlidingWindowLimiter(2, 60)
    agent = await create_agent(client, tools=[])
    conv = await create_conversation(client, agent["id"])
    for _ in range(2):
        fake_provider.model.responses = [reply("ok")]
        resp = await client.post(
            f"/api/conversations/{conv['id']}/messages", json={"content": "hi"}
        )
        assert resp.status_code == 200
    resp = await client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "hi"})
    assert resp.status_code == 429 and "try again" in resp.json()["detail"]


def test_production_refuses_unsafe_settings(settings: Settings) -> None:
    unsafe = settings.model_copy(update={"environment": "production"})
    with pytest.raises(RuntimeError, match="COOKIE_SECURE"):
        create_app(unsafe)
    safe = settings.model_copy(
        update={
            "environment": "production",
            "jwt_secret": SecretStr("s" * 40),
            "secret_encryption_key": SecretStr(Fernet.generate_key().decode()),
            "cookie_secure": True,
            "cors_origins": "https://agents.example.com",
            "database_url": "postgresql+asyncpg://eaa:strong@db:5432/eaa",
        }
    )
    assert safe.production_problems() == []
    create_app(safe)  # does not raise
