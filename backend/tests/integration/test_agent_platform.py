"""Agent versions (draft vs published), playground, duplicate, import/export, templates;
skill versions, tags, search, import/export."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Skill
from tests.conftest import UserClientFactory
from tests.fakes import FakeProvider, reply
from tests.sse_helpers import create_agent, create_conversation, send_message


async def _skill(client: AsyncClient, slug: str, content: str, **extra: Any) -> dict[str, Any]:
    resp = await client.post(
        "/api/skills", json={"slug": slug, "name": slug.title(), "content_md": content} | extra
    )
    assert resp.status_code == 201, resp.text
    skill: dict[str, Any] = resp.json()
    return skill


def _system_prompt(fake: FakeProvider, index: int = -1) -> str:
    return str(fake.model.prompts[index][0].content)


async def test_publish_and_status(client: AsyncClient) -> None:
    agent = await create_agent(client, tools=[], system_prompt="v1 prompt")
    assert (agent["published_version"], agent["has_unpublished_changes"]) == (None, True)

    resp = await client.post(f"/api/agents/{agent['id']}/publish", json={"note": "first"})
    assert resp.status_code == 201 and resp.json()["version"] == 1
    current = (await client.get(f"/api/agents/{agent['id']}")).json()
    assert (current["published_version"], current["has_unpublished_changes"]) == (1, False)

    body = {**_write(current), "system_prompt": "v2 prompt"}
    edited = (await client.put(f"/api/agents/{agent['id']}", json=body)).json()
    assert (edited["published_version"], edited["has_unpublished_changes"]) == (1, True)
    versions = (await client.get(f"/api/agents/{agent['id']}/versions")).json()
    assert [(v["version"], v["note"]) for v in versions] == [(1, "first")]
    v1 = (await client.get(f"/api/agents/{agent['id']}/versions/1")).json()
    assert v1["write_config"]["system_prompt"] == "v1 prompt"
    assert (await client.get(f"/api/agents/{agent['id']}/versions/9")).status_code == 404


def _write(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": agent["name"],
        "description": agent["description"],
        "provider": agent["provider"],
        "connection_id": agent["connection_id"],
        "model": agent["model"],
        "model_params": {k: v for k, v in agent["model_params"].items() if v is not None},
        "system_prompt": agent["system_prompt"],
        "skill_ids": [s["id"] for s in agent["skills"]],
        "tools": agent["tools"],
        "max_tool_calls": agent["max_tool_calls"],
        "run_timeout_s": agent["run_timeout_s"],
    }


async def test_chat_runs_published_version_and_playground_runs_draft(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    skill = await _skill(client, "style", "PUBLISHED SKILL TEXT")
    agent = await create_agent(
        client, tools=[], system_prompt="published prompt", skill_ids=[skill["id"]]
    )
    await client.post(f"/api/agents/{agent['id']}/publish", json={})
    # Edit both the draft and the skill afterwards.
    current = (await client.get(f"/api/agents/{agent['id']}")).json()
    await client.put(
        f"/api/agents/{agent['id']}", json={**_write(current), "system_prompt": "draft prompt"}
    )
    await client.put(
        f"/api/skills/{skill['id']}",
        json={"slug": "style", "name": "Style", "content_md": "EDITED SKILL TEXT"},
    )

    fake_provider.model.responses = [reply("chat answer"), reply("playground answer")]
    chat = await create_conversation(client, agent["id"])
    events = await send_message(client, chat["id"], "hi")
    prompt = _system_prompt(fake_provider)
    assert "published prompt" in prompt and "PUBLISHED SKILL TEXT" in prompt  # frozen at publish
    run = (await client.get(f"/api/runs/{events[0]['data']['run_id']}")).json()
    assert run["agent_version"] == 1

    resp = await client.post(
        "/api/conversations", json={"agent_id": agent["id"], "playground": True}
    )
    playground = resp.json()
    assert playground["kind"] == "playground"
    events = await send_message(client, playground["id"], "hi")
    prompt = _system_prompt(fake_provider)
    assert "draft prompt" in prompt and "EDITED SKILL TEXT" in prompt
    run = (await client.get(f"/api/runs/{events[0]['data']['run_id']}")).json()
    assert run["agent_version"] is None

    # Playground conversations stay out of the normal history.
    listed = [c["id"] for c in (await client.get("/api/conversations")).json()]
    assert chat["id"] in listed and playground["id"] not in listed
    pg = [c["id"] for c in (await client.get("/api/conversations?kind=playground")).json()]
    assert pg == [playground["id"]]


async def test_unpublished_agents_keep_running_their_draft(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    agent = await create_agent(client, tools=[], system_prompt="only draft")
    conv = await create_conversation(client, agent["id"])
    fake_provider.model.responses = [reply("ok")]
    events = await send_message(client, conv["id"], "hi")
    assert "only draft" in _system_prompt(fake_provider)
    run = (await client.get(f"/api/runs/{events[0]['data']['run_id']}")).json()
    assert run["agent_version"] is None


async def test_restore_version_into_draft(client: AsyncClient) -> None:
    keep = await _skill(client, "keep", "k")
    gone = await _skill(client, "gone", "g")
    agent = await create_agent(
        client, tools=[], system_prompt="original", skill_ids=[keep["id"], gone["id"]]
    )
    await client.post(f"/api/agents/{agent['id']}/publish", json={})
    current = (await client.get(f"/api/agents/{agent['id']}")).json()
    await client.put(
        f"/api/agents/{agent['id']}",
        json={**_write(current), "system_prompt": "changed", "skill_ids": []},
    )
    await client.delete(f"/api/skills/{gone['id']}")

    resp = await client.post(f"/api/agents/{agent['id']}/versions/1/restore")
    assert resp.status_code == 200
    restored = resp.json()
    assert restored["system_prompt"] == "original"
    assert [s["slug"] for s in restored["skills"]] == ["keep"]  # deleted skill dropped
    assert restored["has_unpublished_changes"] is True  # skills differ from v1


async def test_versions_rbac_and_isolation(
    client: AsyncClient, make_client: UserClientFactory
) -> None:
    agent = await create_agent(client, tools=[])
    other = await make_client("x@example.com")
    for method, path in (
        ("POST", f"/api/agents/{agent['id']}/publish"),
        ("GET", f"/api/agents/{agent['id']}/versions"),
        ("GET", f"/api/agents/{agent['id']}/export"),
        ("POST", f"/api/agents/{agent['id']}/duplicate"),
    ):
        resp = await other.request(method, path, json={} if method == "POST" else None)
        assert resp.status_code == 404, path
    viewer = await make_client("viewer@example.com")
    await client.post("/api/members", json={"email": "viewer@example.com", "role": "viewer"})
    viewer.headers["X-Workspace-Id"] = (await client.get("/api/auth/me")).json()[
        "current_workspace_id"
    ]
    assert (await viewer.post(f"/api/agents/{agent['id']}/publish", json={})).status_code == 403
    assert (await viewer.get(f"/api/agents/{agent['id']}/versions")).status_code == 200


async def test_duplicate(client: AsyncClient) -> None:
    skill = await _skill(client, "s1", "x")
    agent = await create_agent(client, system_prompt="be exact", skill_ids=[skill["id"]])
    resp = await client.post(f"/api/agents/{agent['id']}/duplicate", json={})
    assert resp.status_code == 201
    copy = resp.json()
    assert copy["id"] != agent["id"] and copy["name"] == f"Copy of {agent['name']}"
    assert copy["system_prompt"] == "be exact" and [s["id"] for s in copy["skills"]] == [
        skill["id"]
    ]
    assert copy["published_version"] is None
    named = await client.post(f"/api/agents/{agent['id']}/duplicate", json={"name": "Twin"})
    assert named.json()["name"] == "Twin"


async def test_export_import_roundtrip(
    client: AsyncClient, make_client: UserClientFactory, session: AsyncSession
) -> None:
    skill = await _skill(client, "cite", "Always cite.", category="writing", tags=["Quality"])
    agent = await create_agent(
        client,
        system_prompt="Researcher",
        skill_ids=[skill["id"]],
        model_params={"temperature": 0.2},
    )
    doc = (await client.get(f"/api/agents/{agent['id']}/export")).json()
    assert doc["format"] == "eaa.agent/v1"
    text = str(doc)
    assert agent["id"] not in text and skill["id"] not in text  # no ids leak
    assert doc["skills"][0]["tags"] == ["quality"]

    other = await make_client("importer@example.com")
    resp = await other.post("/api/agents/import", json=doc)
    assert resp.status_code == 201, resp.text
    result = resp.json()
    assert (result["created_skills"], result["reused_skills"]) == (["cite"], [])
    imported = (await other.get(f"/api/agents/{result['agent_id']}")).json()
    assert (
        imported["system_prompt"] == "Researcher" and imported["model_params"]["temperature"] == 0.2
    )
    assert [s["slug"] for s in imported["skills"]] == ["cite"]

    again = (await other.post("/api/agents/import", json=doc)).json()
    assert (again["created_skills"], again["reused_skills"]) == ([], ["cite"])


async def test_import_validation_is_atomic(client: AsyncClient, session: AsyncSession) -> None:
    doc = {
        "format": "eaa.agent/v1",
        "agent": {
            "name": "Bad",
            "model": "tools:1b",
            "skills": ["new-skill"],
            "tools": [{"name": "rm_rf"}],
        },
        "skills": [{"slug": "new-skill", "name": "New"}],
    }
    resp = await client.post("/api/agents/import", json=doc)
    assert resp.status_code == 422 and "Unknown tool" in resp.json()["detail"]
    assert await session.scalar(select(func.count()).select_from(Skill)) == 0  # nothing created

    missing = {**doc, "agent": {**doc["agent"], "tools": [], "skills": ["not-included"]}}
    assert (await client.post("/api/agents/import", json=missing)).status_code == 422
    conn = {**doc, "agent": {**doc["agent"], "tools": [], "connection_name": "Nope"}}
    resp = await client.post("/api/agents/import", json=conn)
    assert resp.status_code == 422 and "Add a provider" in resp.json()["detail"]
    wrong_format = {**doc, "format": "something/else"}
    assert (await client.post("/api/agents/import", json=wrong_format)).status_code == 422


async def test_templates(client: AsyncClient, settings: Settings) -> None:
    templates = (await client.get("/api/agent-templates")).json()
    ids = {t["id"] for t in templates}
    assert {"research-assistant", "calculator-helper"} <= ids
    research = next(t for t in templates if t["id"] == "research-assistant")
    assert research["tools"] == [{"name": "file_reader", "config": {}, "requires_approval": False}]
    (settings.skills_dir / "tmpl.md").write_text(
        "---\nslug: tmpl\nname: Template\ncategory: writing\ntags: [a, b]\n---\nBody",
        encoding="utf-8",
    )
    try:
        skills = (await client.get("/api/skill-templates")).json()
        assert [(s["slug"], s["category"], s["tags"]) for s in skills] == [
            ("tmpl", "writing", ["a", "b"])
        ]
    finally:
        (settings.skills_dir / "tmpl.md").unlink()


async def test_skill_versions_tags_search_and_markdown(client: AsyncClient) -> None:
    skill = await _skill(client, "tone", "v1 body", category="writing", tags=["Style", "style"])
    assert skill["tags"] == ["style"] and skill["version"] == 1
    sid = skill["id"]
    updated = (
        await client.put(
            f"/api/skills/{sid}",
            json={
                "slug": "tone",
                "name": "Tone",
                "content_md": "v2 body",
                "category": "writing",
                "tags": ["style"],
            },
        )
    ).json()
    assert updated["version"] == 2
    # Changing only tags does not create a version.
    same = (
        await client.put(
            f"/api/skills/{sid}",
            json={
                "slug": "tone",
                "name": "Tone",
                "content_md": "v2 body",
                "category": "writing",
                "tags": ["voice"],
            },
        )
    ).json()
    assert same["version"] == 2
    versions = (await client.get(f"/api/skills/{sid}/versions")).json()
    assert [(v["version"], v["content_md"]) for v in versions] == [(1, "v1 body")]
    restored = (await client.post(f"/api/skills/{sid}/versions/1/restore")).json()
    assert (restored["content_md"], restored["version"]) == ("v1 body", 3)

    await _skill(client, "other", "x", category="analysis", tags=["numbers"])
    assert [s["slug"] for s in (await client.get("/api/skills?tag=voice")).json()] == ["tone"]
    assert [s["slug"] for s in (await client.get("/api/skills?category=analysis")).json()] == [
        "other"
    ]
    assert [s["slug"] for s in (await client.get("/api/skills?q=OTH")).json()] == ["other"]

    md = (await client.get(f"/api/skills/{sid}/export")).text
    assert (
        md.startswith("---\nslug: tone\n")
        and "tags:\n- voice" in md
        and md.strip().endswith("v1 body")
    )
    await client.delete(f"/api/skills/{sid}")
    imported = await client.post("/api/skills/import", json={"markdown": md})
    assert imported.status_code == 201 and imported.json()["tags"] == ["voice"]
    assert (await client.post("/api/skills/import", json={"markdown": md})).status_code == 409
    assert (
        await client.post("/api/skills/import", json={"markdown": "no frontmatter"})
    ).status_code == 422
    bad_tag = {"slug": "t2", "name": "T", "tags": ["no/slashes"]}
    assert (await client.post("/api/skills", json=bad_tag)).status_code == 422


async def test_connection_pinned_by_published_version_cannot_be_deleted(
    client: AsyncClient,
) -> None:
    conn = (
        await client.post(
            "/api/providers", json={"name": "OpenAI", "kind": "openai", "api_key": "sk-0123456789"}
        )
    ).json()
    agent = await create_agent(client, tools=[], model="cloud-model", connection_id=conn["id"])
    await client.post(f"/api/agents/{agent['id']}/publish", json={})
    current = (await client.get(f"/api/agents/{agent['id']}")).json()
    # Move the draft back to the built-in provider: the published version still uses the connection.
    await client.put(
        f"/api/agents/{agent['id']}",
        json={**_write(current), "connection_id": None, "provider": "ollama", "model": "tools:1b"},
    )
    assert (await client.delete(f"/api/providers/{conn['id']}")).status_code == 409
