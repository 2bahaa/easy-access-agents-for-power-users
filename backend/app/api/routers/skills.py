import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import PlainTextResponse

from app.api.deps import PrincipalDep, SessionDep, SettingsDep
from app.schemas.platform import SkillImportRequest, SkillVersionRead
from app.schemas.skills import SkillRead, SkillSummary, SkillWrite
from app.services import skill_service
from app.skills.loader import to_skill_markdown

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
async def list_skills(
    principal: PrincipalDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    tag: Annotated[str | None, Query(max_length=40)] = None,
    category: Annotated[str | None, Query(max_length=50)] = None,
) -> list[SkillSummary]:
    skills = await skill_service.list_skills(
        session, principal.workspace_id, q=q, tag=tag, category=category
    )
    return [SkillSummary.model_validate(s) for s in skills]


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_skill(
    data: SkillImportRequest, principal: PrincipalDep, session: SessionDep
) -> SkillRead:
    """Create a skill from Markdown with YAML frontmatter (slug, name, description, …)."""
    return SkillRead.model_validate(
        await skill_service.import_markdown(session, principal, data.markdown)
    )


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


@router.get("/{skill_id}/versions")
async def list_skill_versions(
    skill_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[SkillVersionRead]:
    versions = await skill_service.list_versions(session, principal, skill_id)
    return [SkillVersionRead.model_validate(v) for v in versions]


@router.post("/{skill_id}/versions/{version}/restore")
async def restore_skill_version(
    skill_id: uuid.UUID, version: int, principal: PrincipalDep, session: SessionDep
) -> SkillRead:
    skill = await skill_service.restore_version(session, principal, skill_id, version)
    return SkillRead.model_validate(skill)


@router.get("/{skill_id}/export", response_class=PlainTextResponse)
async def export_skill(skill_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> str:
    skill = await skill_service.get_skill(session, skill_id, principal.workspace_id)
    return to_skill_markdown(skill_service.to_write(skill))


templates_router = APIRouter(tags=["skills"])


@templates_router.get("/skill-templates")
async def skill_templates(principal: PrincipalDep, settings: SettingsDep) -> list[SkillWrite]:
    return skill_service.templates(settings.skills_dir)
