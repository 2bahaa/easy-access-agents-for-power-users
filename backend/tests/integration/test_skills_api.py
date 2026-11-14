import uuid
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill
from app.services.skill_service import seed_builtin_skills


def skill_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "slug": "polite-tone",
        "name": "Polite tone",
        "description": "Be polite",
        "content_md": "# Polite\n\nAlways say please.",
    } | overrides


async def test_skill_crud_roundtrip(client: AsyncClient) -> None:
    created = await client.post("/api/skills", json=skill_payload())
    assert created.status_code == 201, created.text
    skill = created.json()
    assert skill["slug"] == "polite-tone"
    assert skill["is_builtin"] is False

    listed = (await client.get("/api/skills")).json()
    assert any(s["id"] == skill["id"] for s in listed)
    assert all("content_md" not in s for s in listed)

    fetched = await client.get(f"/api/skills/{skill['id']}")
    assert fetched.json()["content_md"] == "# Polite\n\nAlways say please."

    updated = await client.put(
        f"/api/skills/{skill['id']}", json=skill_payload(name="Very polite", content_md="New")
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Very polite"
    assert updated.json()["content_md"] == "New"

    assert (await client.delete(f"/api/skills/{skill['id']}")).status_code == 204
    assert (await client.get(f"/api/skills/{skill['id']}")).status_code == 404


async def test_duplicate_slug_conflicts(client: AsyncClient) -> None:
    assert (await client.post("/api/skills", json=skill_payload())).status_code == 201
    dup = await client.post("/api/skills", json=skill_payload(name="Other"))
    assert dup.status_code == 409
    assert dup.headers["content-type"].startswith("application/problem+json")
    assert "already exists" in dup.json()["detail"]


async def test_update_to_taken_slug_conflicts(client: AsyncClient) -> None:
    await client.post("/api/skills", json=skill_payload())
    other = (await client.post("/api/skills", json=skill_payload(slug="other"))).json()
    resp = await client.put(f"/api/skills/{other['id']}", json=skill_payload())
    assert resp.status_code == 409


async def test_invalid_skill_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/skills", json=skill_payload(slug="Not A Slug"))
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["loc"][-1] == "slug"


async def test_unknown_skill_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await client.get(f"/api/skills/{missing}")).status_code == 404
    assert (await client.put(f"/api/skills/{missing}", json=skill_payload())).status_code == 404
    assert (await client.delete(f"/api/skills/{missing}")).status_code == 404


async def test_seed_builtin_skills_is_idempotent(session: AsyncSession, tmp_path: Path) -> None:
    (tmp_path / "s.md").write_text(
        "---\nslug: seeded\nname: Seeded\ndescription: d\n---\nbody", encoding="utf-8"
    )
    assert await seed_builtin_skills(session, tmp_path) == 1
    assert await seed_builtin_skills(session, tmp_path) == 0
    skill = await session.scalar(select(Skill).where(Skill.slug == "seeded"))
    assert skill is not None and skill.is_builtin and skill.content_md == "body"


async def test_seed_does_not_overwrite_user_edits(session: AsyncSession, tmp_path: Path) -> None:
    session.add(Skill(slug="seeded", name="Mine", description="", content_md="edited"))
    await session.commit()
    (tmp_path / "s.md").write_text("---\nslug: seeded\nname: Seeded\n---\nbody", encoding="utf-8")
    assert await seed_builtin_skills(session, tmp_path) == 0
    skill = await session.scalar(select(Skill).where(Skill.slug == "seeded"))
    assert skill is not None and skill.content_md == "edited"
