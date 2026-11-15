"""Human approvals of held tool calls, and approval policies."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import PrincipalDep, SessionDep
from app.services import approval_service

router = APIRouter(tags=["approvals"])


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    conversation_id: uuid.UUID | None  # None for workflow approvals
    agent_id: uuid.UUID | None
    call_id: str
    tool_name: str
    args: dict[str, Any]
    status: str
    edited_args: dict[str, Any] | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    note: str
    created_at: datetime
    expires_at: datetime


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    # Approve with corrected arguments (still validated against the tool's schema when run).
    args: dict[str, Any] | None = None
    note: str = Field(default="", max_length=500)


class DecisionResult(BaseModel):
    approval: ApprovalRead
    # Set when this was the last pending decision: the run that now continues.
    continuation_run_id: uuid.UUID | None


class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_pattern: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_*?\-\[\]]+$")
    agent_id: uuid.UUID | None = None


class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tool_pattern: str
    agent_id: uuid.UUID | None
    created_at: datetime


@router.get("/approvals")
async def list_approvals(
    principal: PrincipalDep,
    session: SessionDep,
    status_: Annotated[
        Literal["pending", "approved", "rejected", "expired", "cancelled", "all"],
        Query(alias="status"),
    ] = "pending",
    run_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> list[ApprovalRead]:
    rows = await approval_service.list_requests(
        session,
        principal,
        status=None if status_ == "all" else status_,
        run_id=run_id,
        conversation_id=conversation_id,
    )
    return [ApprovalRead.model_validate(r) for r in rows]


@router.post("/approvals/{approval_id}/decide")
async def decide(
    approval_id: uuid.UUID, data: DecisionRequest, principal: PrincipalDep, session: SessionDep
) -> DecisionResult:
    req, continuation = await approval_service.decide(
        session,
        principal,
        approval_id,
        data.decision == "approve",
        edited_args=data.args,
        note=data.note,
    )
    return DecisionResult(
        approval=ApprovalRead.model_validate(req),
        continuation_run_id=continuation.id if continuation else None,
    )


@router.get("/approval-policies")
async def list_policies(principal: PrincipalDep, session: SessionDep) -> list[PolicyRead]:
    return [
        PolicyRead.model_validate(p)
        for p in await approval_service.list_policies(session, principal)
    ]


@router.post("/approval-policies", status_code=status.HTTP_201_CREATED)
async def create_policy(
    data: PolicyCreate, principal: PrincipalDep, session: SessionDep
) -> PolicyRead:
    policy = await approval_service.create_policy(
        session, principal, data.tool_pattern, data.agent_id
    )
    return PolicyRead.model_validate(policy)


@router.delete("/approval-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(policy_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await approval_service.delete_policy(session, principal, policy_id)
