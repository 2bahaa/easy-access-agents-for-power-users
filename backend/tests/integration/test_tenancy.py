"""Tenant isolation, RBAC, API keys and the audit log (negative tests first)."""

import uuid
from typing import Any

from httpx import AsyncClient

from app.config import Settings
from tests.conftest import UserClientFactory
from tests.fakes import FakeProvider, reply, tool_call
from tests.sse_helpers import create_agent, create_conversation, parse_sse, send_message


async def _skill(client: AsyncClient, slug: str = "tone") -> dict[str, Any]:
    resp = await client.post(
        "/api/skills", json={"slug": slug, "name": "Tone", "content_md": "Be kind."}
    )
    assert resp.status_code == 201, resp.text
    skill: dict[str, Any] = resp.json()
    return skill


async def _me(client: AsyncClient) -> dict[str, Any]:
    me: dict[str, Any] = (await client.get("/api/auth/me")).json()
    return me


async def test_users_never_see_other_tenants_data(
    client: AsyncClient, make_client: UserClientFactory, fake_provider: FakeProvider
) -> None:
    fake_provider.model.responses = [reply("A's answer.")]
    agent = await create_agent(client, tools=[])
    skill = await _skill(client)
    conv = await create_conversation(client, agent["id"])
    events = await send_message(client, conv["id"], "secret question")
    run_id = events[0]["data"]["run_id"]

    other = await make_client("mallory@example.com")
    # Lists are scoped.
    for path in ("/api/agents", "/api/skills", "/api/conversations"):
        assert (await other.get(path)).json() == [], path
    # Direct access by id is indistinguishable from "does not exist".
    for path in (
        f"/api/agents/{agent['id']}",
        f"/api/skills/{skill['id']}",
        f"/api/conversations/{conv['id']}",
        f"/api/runs/{run_id}",
        f"/api/runs/{run_id}/events",
        f"/api/runs/{run_id}/stream",
    ):
        assert (await other.get(path)).status_code == 404, path
    payload = {"name": "pwn", "model": "tools:1b"}
    assert (await other.put(f"/api/agents/{agent['id']}", json=payload)).status_code == 404
    assert (await other.delete(f"/api/agents/{agent['id']}")).status_code == 404
    assert (await other.delete(f"/api/skills/{skill['id']}")).status_code == 404
    assert (await other.delete(f"/api/conversations/{conv['id']}")).status_code == 404
    assert (await other.post(f"/api/runs/{run_id}/cancel")).status_code == 404
    message = {"content": "hijack"}
    resp = await other.post(f"/api/conversations/{conv['id']}/messages", json=message)
    assert resp.status_code == 404

    # Cross-tenant references are rejected when creating resources.
    resp = await other.post("/api/conversations", json={"agent_id": agent["id"]})
    assert resp.status_code == 422
    resp = await other.post(
        "/api/agents", json={"name": "x", "model": "tools:1b", "skill_ids": [skill["id"]]}
    )
    assert resp.status_code == 422

    # The owner still has everything.
    assert len((await client.get("/api/agents")).json()) == 1


async def test_workspace_header_cannot_reach_foreign_workspaces(
    client: AsyncClient, make_client: UserClientFactory
) -> None:
    a_ws = (await _me(client))["current_workspace_id"]
    other = await make_client("eve@example.com")
    for value in (a_ws, str(uuid.uuid4()), "not-a-uuid"):
        resp = await other.get("/api/agents", headers={"X-Workspace-Id": value})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Unknown workspace"


async def test_same_skill_slug_in_different_workspaces(
    client: AsyncClient, make_client: UserClientFactory
) -> None:
    other = await make_client("b@example.com")
    await _skill(client, "shared-slug")
    await _skill(other, "shared-slug")  # slugs are unique per workspace only
    resp = await client.post("/api/skills", json={"slug": "shared-slug", "name": "Dup"})
    assert resp.status_code == 409


async def test_file_sandbox_is_per_workspace(
    client: AsyncClient,
    make_client: UserClientFactory,
    fake_provider: FakeProvider,
    settings: Settings,
) -> None:
    a_slug = (await _me(client))["organizations"][0]["workspaces"][0]["slug"]
    (settings.workspace_dir / a_slug).mkdir(parents=True, exist_ok=True)
    (settings.workspace_dir / a_slug / "secret.txt").write_text("A-only data", encoding="utf-8")

    async def read_secret(c: AsyncClient) -> dict[str, Any]:
        fake_provider.model.responses = [
            reply("", tool_call("file_reader", {"path": "secret.txt"}, "f1")),
            reply("done"),
        ]
        agent = await create_agent(c, tools=[{"name": "file_reader"}])
        conv = await create_conversation(c, agent["id"])
        events = await send_message(c, conv["id"], "read it")
        return next(
            e
            for e in events
            if e["event"].startswith("tool.call.") and e["event"] != "tool.call.started"
        )

    own = await read_secret(client)
    assert own["event"] == "tool.call.completed" and own["data"]["result"] == "A-only data"

    other = await make_client("c@example.com")
    foreign = await read_secret(other)
    assert foreign["event"] == "tool.call.failed"
    for slug_escape in (f"../{a_slug}/secret.txt",):
        fake_provider.model.responses = [
            reply("", tool_call("file_reader", {"path": slug_escape}, "f2")),
            reply("done"),
        ]
        agent = await create_agent(other, tools=[{"name": "file_reader"}])
        conv = await create_conversation(other, agent["id"])
        events = await send_message(other, conv["id"], "escape")
        assert any(e["event"] == "tool.call.failed" for e in events)


async def test_roles_are_enforced(
    client: AsyncClient, make_client: UserClientFactory, fake_provider: FakeProvider
) -> None:
    viewer = await make_client("viewer@example.com")
    editor = await make_client("editor@example.com")
    ws = (await _me(client))["current_workspace_id"]
    assert (
        await client.post("/api/members", json={"email": "viewer@example.com", "role": "viewer"})
    ).status_code == 201
    assert (
        await client.post("/api/members", json={"email": "editor@example.com", "role": "editor"})
    ).status_code == 201
    viewer.headers["X-Workspace-Id"] = ws
    editor.headers["X-Workspace-Id"] = ws

    agent = await create_agent(client, tools=[])
    conv = await create_conversation(client, agent["id"])

    # Viewer: read-only.
    assert (await viewer.get("/api/agents")).status_code == 200
    assert (await viewer.get(f"/api/conversations/{conv['id']}")).status_code == 200
    assert (
        await viewer.post("/api/agents", json={"name": "v", "model": "tools:1b"})
    ).status_code == 403
    assert (await viewer.delete(f"/api/agents/{agent['id']}")).status_code == 403
    assert (await viewer.post("/api/skills", json={"slug": "v", "name": "v"})).status_code == 403
    resp = await viewer.post(f"/api/conversations/{conv['id']}/messages", json={"content": "hi"})
    assert resp.status_code == 403
    assert (
        await viewer.post("/api/api-keys", json={"name": "k", "role": "viewer"})
    ).status_code == 403
    assert (await viewer.get("/api/audit")).status_code == 403

    # Editor: builds and runs, but cannot administer.
    fake_provider.model.responses = [reply("ok")]
    assert (
        await editor.post("/api/agents", json={"name": "e", "model": "tools:1b"})
    ).status_code == 201
    assert (
        parse_sse(
            (
                await editor.post(
                    f"/api/conversations/{conv['id']}/messages", json={"content": "hi"}
                )
            ).text
        )[-1]["event"]
        == "run.completed"
    )
    assert (
        await editor.post("/api/members", json={"email": "x@example.com", "role": "viewer"})
    ).status_code == 403
    assert (await editor.post("/api/workspaces", json={"name": "W2"})).status_code == 403
    assert (await editor.get("/api/audit")).status_code == 403


async def test_member_administration_rules(
    client: AsyncClient, make_client: UserClientFactory
) -> None:
    admin = await make_client("admin@example.com")
    await make_client("someone@example.com")
    owner_me = await _me(client)
    owner_id = owner_me["user"]["id"]
    assert (
        await client.post("/api/members", json={"email": "admin@example.com", "role": "admin"})
    ).status_code == 201
    admin.headers["X-Workspace-Id"] = owner_me["current_workspace_id"]

    # Unknown users and duplicates.
    assert (
        await client.post("/api/members", json={"email": "ghost@example.com"})
    ).status_code == 422
    assert (
        await client.post("/api/members", json={"email": "admin@example.com"})
    ).status_code == 409
    # Admins cannot grant owner, nor change or remove an owner.
    assert (
        await admin.post("/api/members", json={"email": "someone@example.com", "role": "owner"})
    ).status_code == 403
    assert (
        await admin.patch(f"/api/members/{owner_id}", json={"role": "viewer"})
    ).status_code == 403
    assert (await admin.delete(f"/api/members/{owner_id}")).status_code == 403
    # The last owner cannot be demoted or removed.
    assert (
        await client.patch(f"/api/members/{owner_id}", json={"role": "admin"})
    ).status_code == 409
    assert (await client.delete(f"/api/members/{owner_id}")).status_code == 409

    members = (await client.get("/api/members")).json()
    assert {m["email"]: m["role"] for m in members} == {
        "owner@example.com": "owner",
        "admin@example.com": "admin",
    }
    # Admins can create workspaces in the organization; members see them.
    created = await admin.post("/api/workspaces", json={"name": "Research"})
    assert created.status_code == 201
    names = [w["name"] for w in (await client.get("/api/workspaces")).json()]
    assert "Research" in names


async def test_api_keys(
    client: AsyncClient, make_client: UserClientFactory, anon_client: AsyncClient
) -> None:
    created = await client.post("/api/api-keys", json={"name": "CI", "role": "viewer"})
    assert created.status_code == 201
    key = created.json()
    token = key["token"]
    assert token.startswith("eaa_") and key["role"] == "viewer"
    listed = (await client.get("/api/api-keys")).json()
    assert [k["id"] for k in listed] == [key["id"]] and "token" not in listed[0]

    as_key = {"Authorization": f"Bearer {token}"}
    assert (await anon_client.get("/api/agents", headers=as_key)).status_code == 200
    # Viewer key: read-only; keys cannot mint keys.
    resp = await anon_client.post(
        "/api/agents", headers=as_key, json={"name": "k", "model": "tools:1b"}
    )
    assert resp.status_code == 403
    resp = await anon_client.post(
        "/api/api-keys", headers=as_key, json={"name": "k2", "role": "viewer"}
    )
    assert resp.status_code == 403
    # A key is bound to its workspace: the header cannot move it elsewhere.
    other = await make_client("z@example.com")
    other_ws = (await _me(other))["current_workspace_id"]
    resp = await anon_client.get("/api/agents", headers=as_key | {"X-Workspace-Id": other_ws})
    assert resp.status_code == 200 and resp.json() == []  # still the key's own workspace
    agent = await create_agent(other, tools=[])
    assert (await anon_client.get(f"/api/agents/{agent['id']}", headers=as_key)).status_code == 404

    # Malformed and revoked keys.
    tampered = {"Authorization": f"Bearer {token[:-2]}xx"}
    assert (await anon_client.get("/api/agents", headers=tampered)).status_code == 401
    assert (await client.delete(f"/api/api-keys/{key['id']}")).status_code == 204
    assert (await anon_client.get("/api/agents", headers=as_key)).status_code == 401
    # Other users cannot revoke your keys.
    k2 = (await client.post("/api/api-keys", json={"name": "two", "role": "editor"})).json()
    assert (await other.delete(f"/api/api-keys/{k2['id']}")).status_code == 404


async def test_key_role_cannot_exceed_creator(
    client: AsyncClient, make_client: UserClientFactory
) -> None:
    editor = await make_client("ed@example.com")
    assert (
        await client.post("/api/members", json={"email": "ed@example.com", "role": "editor"})
    ).status_code == 201
    editor.headers["X-Workspace-Id"] = (await _me(client))["current_workspace_id"]
    resp = await editor.post("/api/api-keys", json={"name": "too-strong", "role": "admin"})
    assert resp.status_code == 403
    assert (
        await editor.post("/api/api-keys", json={"name": "fine", "role": "editor"})
    ).status_code == 201


async def test_audit_log_records_security_events(
    client: AsyncClient, make_client: UserClientFactory
) -> None:
    await make_client("audited@example.com")
    await client.post("/api/members", json={"email": "audited@example.com", "role": "viewer"})
    key = (await client.post("/api/api-keys", json={"name": "k", "role": "viewer"})).json()
    await client.delete(f"/api/api-keys/{key['id']}")
    agent = await create_agent(client, tools=[])
    await client.delete(f"/api/agents/{agent['id']}")

    entries = (await client.get("/api/audit")).json()
    actions = [e["action"] for e in entries]
    for expected in (
        "user.registered",
        "member.added",
        "api_key.created",
        "api_key.revoked",
        "agent.deleted",
    ):
        assert expected in actions, expected
    ids = [e["id"] for e in entries]
    assert ids == sorted(ids, reverse=True)  # newest first
    page = (await client.get(f"/api/audit?limit=2&before={entries[1]['id']}")).json()
    assert all(e["id"] < entries[1]["id"] for e in page) and len(page) <= 2
    # Another organization's log is not visible.
    other = await make_client("stranger@example.com")
    assert all(e["action"] == "user.registered" for e in (await other.get("/api/audit")).json())
