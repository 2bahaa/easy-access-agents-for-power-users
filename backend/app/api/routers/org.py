"""Organization administration: workspaces, members, API keys and the audit log.
All endpoints act on the caller's current organization/workspace."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import PrincipalDep, SessionDep, SettingsDep
from app.schemas.auth import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    AuditEntryRead,
    MemberAdd,
    MemberRead,
    MemberUpdate,
    WorkspaceCreate,
    WorkspaceRead,
)
from app.services import audit_service, skill_service, tenancy_service

router = APIRouter(tags=["organization"])


@router.get("/workspaces")
async def list_workspaces(principal: PrincipalDep, session: SessionDep) -> list[WorkspaceRead]:
    items = await tenancy_service.list_workspaces(session, principal)
    return [WorkspaceRead.model_validate(w) for w in items]


@router.post("/workspaces", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    data: WorkspaceCreate, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> WorkspaceRead:
    workspace = await tenancy_service.add_workspace(session, principal, data.name)
    await skill_service.seed_builtin_skills(session, settings.skills_dir, workspace.id)
    return WorkspaceRead.model_validate(workspace)


@router.get("/members")
async def list_members(principal: PrincipalDep, session: SessionDep) -> list[MemberRead]:
    rows = await tenancy_service.list_members(session, principal)
    return [
        MemberRead(user_id=u.id, email=u.email, name=u.name, role=m.role, joined_at=m.created_at)
        for u, m in rows
    ]


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def add_member(data: MemberAdd, principal: PrincipalDep, session: SessionDep) -> MemberRead:
    user, m = await tenancy_service.add_member(session, principal, data.email, data.role)
    return MemberRead(
        user_id=user.id, email=user.email, name=user.name, role=m.role, joined_at=m.created_at
    )


@router.patch("/members/{user_id}")
async def update_member(
    user_id: uuid.UUID, data: MemberUpdate, principal: PrincipalDep, session: SessionDep
) -> None:
    await tenancy_service.update_member(session, principal, user_id, data.role)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await tenancy_service.remove_member(session, principal, user_id)


@router.get("/api-keys")
async def list_api_keys(principal: PrincipalDep, session: SessionDep) -> list[ApiKeyRead]:
    return [
        ApiKeyRead.model_validate(k)
        for k in await tenancy_service.list_api_keys(session, principal)
    ]


@router.post("/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: ApiKeyCreate, principal: PrincipalDep, session: SessionDep
) -> ApiKeyCreated:
    key, token = await tenancy_service.create_api_key(
        session, principal, data.name, data.role, data.expires_in_days
    )
    return ApiKeyCreated(**ApiKeyRead.model_validate(key).model_dump(), token=token)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await tenancy_service.revoke_api_key(session, principal, key_id)


@router.get("/audit")
async def list_audit(
    principal: PrincipalDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    before: Annotated[int | None, Query(ge=1)] = None,
) -> list[AuditEntryRead]:
    principal.require("admin")
    entries = await audit_service.list_entries(
        session, principal.org_id, limit=limit, before_id=before
    )
    return [AuditEntryRead.model_validate(e) for e in entries]
