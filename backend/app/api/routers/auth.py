from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status

from app.api.deps import PrincipalDep, SessionDep, SettingsDep
from app.api.ratelimit import SlidingWindowLimiter
from app.config import Settings
from app.db.models import User
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    OrgMembershipRead,
    RegisterRequest,
    TokenResponse,
    UserRead,
    WorkspaceRead,
)
from app.services import auth_service, skill_service, tenancy_service
from app.services.auth_service import TokenPair
from app.services.errors import UnauthorizedError

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "eaa_refresh"


def _limiter(request: Request, name: str) -> SlidingWindowLimiter:
    limiter: SlidingWindowLimiter = getattr(request.app.state, name)
    return limiter


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_refresh_cookie(response: Response, settings: Settings, tokens: TokenPair) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,  # not readable by JavaScript
        secure=settings.cookie_secure,
        samesite="strict",  # never sent on cross-site requests (CSRF)
        path="/api/auth",  # only sent to the auth endpoints
    )


def _token_response(tokens: TokenPair) -> TokenResponse:
    return TokenResponse(access_token=tokens.access_token, expires_at=tokens.access_expires_at)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    _limiter(request, "register_limiter").hit(_client(request))
    user, workspace = await auth_service.register(
        session, settings, data.email, data.password, data.name
    )
    await skill_service.seed_builtin_skills(session, settings.skills_dir, workspace.id)
    tokens = await auth_service.issue_tokens(session, settings, user)
    _set_refresh_cookie(response, settings, tokens)
    return _token_response(tokens)


@router.post("/login")
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    key = f"{_client(request)}|{auth_service.normalize_email(data.email)}"
    _limiter(request, "login_limiter").hit(key)
    user = await auth_service.authenticate(session, data.email, data.password)
    tokens = await auth_service.issue_tokens(session, settings, user)  # commits the audit row
    _set_refresh_cookie(response, settings, tokens)
    return _token_response(tokens)


@router.post("/refresh")
async def refresh(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    eaa_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    """Exchange the refresh cookie for a new access token (and a rotated cookie)."""
    try:
        _user, tokens = await auth_service.rotate_refresh_token(session, settings, eaa_refresh)
    except UnauthorizedError:
        response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
        raise
    _set_refresh_cookie(response, settings, tokens)
    return _token_response(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: SessionDep,
    eaa_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    await auth_service.revoke_refresh_token(session, eaa_refresh)
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


@router.get("/me")
async def me(principal: PrincipalDep, session: SessionDep) -> MeResponse:
    user = await session.get(User, principal.user_id)
    assert user is not None  # resolved by the principal dependency
    orgs = await tenancy_service.user_orgs(session, principal.user_id)
    return MeResponse(
        user=UserRead.model_validate(user),
        organizations=[
            OrgMembershipRead(
                id=o.org.id,
                name=o.org.name,
                role=o.role,
                workspaces=[WorkspaceRead.model_validate(w) for w in o.workspaces],
            )
            for o in orgs
        ],
        current_workspace_id=principal.workspace_id,
        role=principal.role,
    )
