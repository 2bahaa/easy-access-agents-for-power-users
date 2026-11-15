import uuid

from fastapi import APIRouter, status

from app.api.deps import PrincipalDep, SessionDep
from app.schemas.skills import SkillRead, SkillSummary, SkillWrite
from app.services import skill_service

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
async def list_skills(principal: PrincipalDep, session: SessionDep) -> list[SkillSummary]:
    skills = await skill_service.list_skills(session, principal.workspace_id)
    return [SkillSummary.model_validate(s) for s in skills]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_skill(data: SkillWrite, principal: PrincipalDep, session: SessionDep) -> SkillRead:
    return SkillRead.model_validate(await skill_service.create_skill(session, principal, data))


@router.get("/{skill_id}")
async def get_skill(skill_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> SkillRead:
    skill = await skill_service.get_skill(session, skill_id, principal.workspace_id)
    return SkillRead.model_validate(skill)


@router.put("/{skill_id}")
async def update_skill(
    skill_id: uuid.UUID, data: SkillWrite, principal: PrincipalDep, session: SessionDep
) -> SkillRead:
    skill = await skill_service.update_skill(session, principal, skill_id, data)
    return SkillRead.model_validate(skill)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await skill_service.delete_skill(session, principal, skill_id)
