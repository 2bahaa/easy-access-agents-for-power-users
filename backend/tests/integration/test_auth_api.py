"""Authentication: registration, login, tokens, refresh rotation, logout, brute-force limits."""

import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AuditLog, RefreshToken, User
from app.main import create_app
from app.security import create_access_token
from tests.conftest import register_user

PASSWORD = "correct horse battery"


async def test_register_returns_token_and_refresh_cookie(anon_client: AsyncClient) -> None:
    resp = await anon_client.post(
        "/api/auth/register", json={"email": "Ada@Example.com", "password": PASSWORD, "name": "Ada"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer" and body["access_token"]
    cookie = resp.headers["set-cookie"]
    assert "eaa_refresh=" in cookie
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api/auth" in cookie

    me = await anon_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    data = me.json()
    assert data["user"]["email"] == "ada@example.com"  # normalized
    assert data["role"] == "owner"
    (org,) = data["organizations"]
    assert org["role"] == "owner" and len(org["workspaces"]) == 1
    assert data["current_workspace_id"] == org["workspaces"][0]["id"]
    assert "password_hash" not in me.text


async def test_registration_validation_and_duplicates(anon_client: AsyncClient) -> None:
    ok = {"email": "x@example.com", "password": PASSWORD}
    assert (await anon_client.post("/api/auth/register", json=ok)).status_code == 201
    assert (await anon_client.post("/api/auth/register", json=ok)).status_code == 409
    upper = ok | {"email": "X@EXAMPLE.COM"}
    assert (await anon_client.post("/api/auth/register", json=upper)).status_code == 409
    weak = {"email": "y@example.com", "password": "short"}
    assert (await anon_client.post("/api/auth/register", json=weak)).status_code == 422
    bad_email = {"email": "not-an-email", "password": PASSWORD}
    assert (await anon_client.post("/api/auth/register", json=bad_email)).status_code == 422


async def test_password_is_hashed_with_argon2(
    anon_client: AsyncClient, session: AsyncSession
) -> None:
    await register_user(anon_client, "h@example.com", PASSWORD)
    user = await session.scalar(select(User).where(User.email == "h@example.com"))
    assert user is not None and user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


async def test_login_success_and_uniform_failures(
    anon_client: AsyncClient, session: AsyncSession
) -> None:
    await register_user(anon_client, "l@example.com", PASSWORD)
    ok = await anon_client.post(
        "/api/auth/login", json={"email": "L@example.com", "password": PASSWORD}
    )
    assert ok.status_code == 200 and ok.json()["access_token"]

    wrong = await anon_client.post(
        "/api/auth/login", json={"email": "l@example.com", "password": "nope-nope-nope"}
    )
    unknown = await anon_client.post(
        "/api/auth/login", json={"email": "who@example.com", "password": PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]  # no account enumeration
    assert wrong.headers["www-authenticate"] == "Bearer"
    actions = list(await session.scalars(select(AuditLog.action)))
    assert actions.count("auth.login_failed") == 2 and "auth.login" in actions


async def test_protected_endpoints_require_valid_tokens(
    anon_client: AsyncClient, settings: Settings
) -> None:
    for path in (
        "/api/agents",
        "/api/skills",
        "/api/tools",
        "/api/providers",
        "/api/conversations",
    ):
        assert (await anon_client.get(path)).status_code == 401, path
    assert (await anon_client.get("/api/health")).status_code == 200  # stays public

    bad = {"Authorization": "Bearer not-a-jwt"}
    assert (await anon_client.get("/api/agents", headers=bad)).status_code == 401
    token = await register_user(anon_client, "t@example.com", PASSWORD)
    me = (
        await anon_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    ).json()
    expired, _ = create_access_token(
        settings.jwt_secret.get_secret_value(), uuid.UUID(me["user"]["id"]), ttl_s=-10
    )
    headers = {"Authorization": f"Bearer {expired}"}
    assert (await anon_client.get("/api/agents", headers=headers)).status_code == 401
    forged, _ = create_access_token("another-secret", uuid.UUID(me["user"]["id"]), ttl_s=300)
    headers = {"Authorization": f"Bearer {forged}"}
    assert (await anon_client.get("/api/agents", headers=headers)).status_code == 401
    basic = {"Authorization": f"Basic {token}"}
    assert (await anon_client.get("/api/agents", headers=basic)).status_code == 401


async def test_refresh_rotates_and_detects_reuse(
    anon_client: AsyncClient, session: AsyncSession
) -> None:
    await register_user(anon_client, "r@example.com", PASSWORD)
    first_cookie = anon_client.cookies.get("eaa_refresh")
    assert first_cookie

    rotated = await anon_client.post("/api/auth/refresh")
    assert rotated.status_code == 200 and rotated.json()["access_token"]
    second_cookie = anon_client.cookies.get("eaa_refresh")
    assert second_cookie and second_cookie != first_cookie

    # Replaying the first (already rotated) token: rejected, and the whole family revoked.
    anon_client.cookies.set("eaa_refresh", first_cookie, path="/api/auth")
    assert (await anon_client.post("/api/auth/refresh")).status_code == 401
    anon_client.cookies.set("eaa_refresh", second_cookie, path="/api/auth")
    assert (await anon_client.post("/api/auth/refresh")).status_code == 401
    active = await session.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
    assert list(active) == []
    assert "auth.refresh_reuse_detected" in list(await session.scalars(select(AuditLog.action)))


async def test_refresh_without_cookie_and_logout(anon_client: AsyncClient) -> None:
    assert (await anon_client.post("/api/auth/refresh")).status_code == 401
    await register_user(anon_client, "o@example.com", PASSWORD)
    assert (await anon_client.post("/api/auth/logout")).status_code == 204
    assert (await anon_client.post("/api/auth/refresh")).status_code == 401


async def test_login_is_rate_limited(anon_client: AsyncClient, settings: Settings) -> None:
    await register_user(anon_client, "rl@example.com", PASSWORD)
    body = {"email": "rl@example.com", "password": "wrong-password-x"}
    for _ in range(settings.login_attempts_per_5min):
        assert (await anon_client.post("/api/auth/login", json=body)).status_code == 401
    blocked = await anon_client.post("/api/auth/login", json=body | {"password": PASSWORD})
    assert blocked.status_code == 429  # even the right password, until the window passes


async def test_registration_can_be_disabled_after_the_first_user(
    settings: Settings, clean_db: None, app: FastAPI
) -> None:
    closed = create_app(settings.model_copy(update={"allow_registration": False}))
    async with closed.router.lifespan_context(closed):
        async with AsyncClient(transport=ASGITransport(app=closed), base_url="http://test") as c:
            first = {"email": "first@example.com", "password": PASSWORD}
            assert (await c.post("/api/auth/register", json=first)).status_code == 201
            second = {"email": "second@example.com", "password": PASSWORD}
            assert (await c.post("/api/auth/register", json=second)).status_code == 403
