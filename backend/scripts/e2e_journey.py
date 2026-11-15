# ruff: noqa: E501  (manual verification script; long check messages)
"""Live end-to-end journey against a running API + real Ollama (no fakes).

Usage: uv run python scripts/e2e_journey.py http://127.0.0.1:8000/api <WORKSPACE_DIR> [model]
(not part of the automated suite; needs a real model and a scratch database).

create/configure an agent → attach tools and a skill → chat with streamed results →
approval pause/approve/resume → build, validate, publish and run a workflow → inspect history.
"""

import json
import pathlib
import shutil
import sys
import time

import httpx

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002/api"
WS_ROOT = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None
MODEL = sys.argv[3] if len(sys.argv) > 3 else "qwen2.5:3b"
c = httpx.Client(base_url=API, timeout=600)
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  — {detail}" if detail else ""), flush=True)


def sse(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        data = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if data:
            out.append(json.loads("\n".join(data)))
    return out


def ok(resp: httpx.Response, code: int = 200) -> dict:
    assert resp.status_code == code, (
        f"{resp.request.method} {resp.request.url} → {resp.status_code} {resp.text[:300]}"
    )
    return resp.json() if resp.content else {}


# 1. Account + workspace
email = f"e2e{int(time.time())}@example.com"
tok = ok(
    c.post("/auth/register", json={"email": email, "password": "e2e-password-123", "name": "E2E"}),
    201,
)
c.headers["Authorization"] = f"Bearer {tok['access_token']}"
me = ok(c.get("/auth/me"))
check("register + authenticate", True, f"role={me.get('role')}")
health = ok(c.get("/health"))
check(
    "health: database + ollama",
    health["database"] == "ok" and health["ollama"] == "ok",
    str(health),
)

slug = next(
    w["slug"]
    for o in me["organizations"]
    for w in o["workspaces"]
    if w["id"] == me["current_workspace_id"]
)
if WS_ROOT:
    (WS_ROOT / slug).mkdir(parents=True, exist_ok=True)
    shutil.copy(WS_ROOT / "notes.txt", WS_ROOT / slug / "notes.txt")

models = ok(c.get("/providers/ollama/models"))
m = next((x for x in models if x["name"] == MODEL), None)
check("model discovery + tools capability", bool(m and m["supports_tools"]), MODEL)

# 2. Agent with tools + skill, published
skills = ok(c.get("/skills"))
agent = ok(
    c.post(
        "/agents",
        json={
            "name": "E2E Assistant",
            "model": MODEL,
            "model_params": {"temperature": 0},
            "system_prompt": "You are concise. Always use tools for arithmetic and for reading files.",
            "skill_ids": [skills[0]["id"]] if skills else [],
            "tools": [
                {"name": "calculator"},
                {"name": "file_reader", "requires_approval": True},
            ],
            "max_tool_calls": 4,
            "run_timeout_s": 900,
        },
    ),
    201,
)
check(
    "create agent with tools + skill",
    len(agent["tools"]) == 2 and len(agent.get("skills", [])) == (1 if skills else 0),
)
pub = ok(c.post(f"/agents/{agent['id']}/publish", json={"note": "e2e"}), 201)
check("publish agent version", pub.get("version") == 1, f"v{pub.get('version')}")

# 3. Chat with streaming + tool call
conv = ok(c.post("/conversations", json={"agent_id": agent["id"]}), 201)
t0 = time.time()
r = c.post(
    f"/conversations/{conv['id']}/messages",
    json={"content": "What is 1234 * 5678? Use the calculator."},
)
events = sse(r.text)
types = [e["type"] for e in events]
tool_done = [e for e in events if e["type"] == "tool.call.completed"]
final = "".join(e.get("text", "") for e in events if e["type"] == "message.delta")
check(
    "chat streams tokens and calls calculator",
    types[-1] == "run.completed" and bool(tool_done) and "message.delta" in types,
    f"{len(events)} events, {time.time() - t0:.0f}s, result={tool_done[0]['result'] if tool_done else None}",
)
check("answer contains 7006652", "7006652" in final.replace(",", ""), final.strip()[:120])

# 4. Approval: file_reader is held
r = c.post(
    f"/conversations/{conv['id']}/messages",
    json={
        "content": "Read the file notes.txt with the file_reader tool and tell me the inverter warranty."
    },
)
events = sse(r.text)
check(
    "sensitive tool call pauses for approval",
    events[-1]["type"] == "run.waiting_approval",
    events[-1]["type"],
)
pending = ok(c.get("/approvals", params={"status": "pending"}))
check("approval appears in inbox", len(pending) == 1, pending[0]["tool_name"] if pending else "")
if pending:
    decided = ok(
        c.post(f"/approvals/{pending[0]['id']}/decide", json={"decision": "approve", "note": "ok"})
    )
    cont = decided.get("continuation_run_id")
    s = c.get(f"/runs/{cont}/stream")
    cevents = sse(s.text)
    read = [e for e in cevents if e["type"] == "tool.call.completed" and e["tool"] == "file_reader"]
    answer = "".join(e.get("text", "") for e in cevents if e["type"] == "message.delta")
    check(
        "approved call runs in continuation",
        bool(read) and cevents[-1]["type"] == "run.completed",
        cevents[-1]["type"],
    )
    check("answer uses file contents", "12" in answer, answer.strip()[:120])
    audit = ok(c.get("/audit"))
    check("approval decision audited", any("approval" in a["action"] for a in audit))

# 5. Workflow: start → agent → llm → end
spec = {
    "schema_version": 1,
    "nodes": [
        {"id": "start", "type": "start", "config": {"inputs": [{"name": "numbers"}]}},
        {
            "id": "calc",
            "type": "agent",
            "config": {
                "agent_id": agent["id"],
                "prompt": "Compute {{ input.numbers }} with the calculator. Reply with the number only.",
            },
        },
        {
            "id": "phrase",
            "type": "llm",
            "config": {
                "model": MODEL,
                "prompt": "Write one short sentence announcing this result: {{ calc }}",
            },
        },
        {"id": "end", "type": "end", "config": {"output": "{{ calc }} | {{ phrase }}"}},
    ],
    "edges": [
        {"source": "start", "target": "calc"},
        {"source": "calc", "target": "phrase"},
        {"source": "phrase", "target": "end"},
    ],
}
v = ok(c.post("/workflows/validate", json=spec))
check("workflow validates", v["valid"], str(v["problems"]))
wf = ok(c.post("/workflows", json={"name": "E2E flow", "spec": spec}), 201)
ok(c.post(f"/workflows/{wf['id']}/publish", json={"note": ""}), 201)
run = ok(c.post(f"/workflows/{wf['id']}/runs", json={"inputs": {"numbers": "250 * 4"}}), 201)
wevents = sse(c.get(f"/runs/{run['id']}/stream").text)
done = [e["node_id"] for e in wevents if e["type"] == "node.completed"]
check("workflow runs every node in order", done == ["start", "calc", "phrase", "end"], str(done))
out = wevents[-1].get("output", "")
check(
    "workflow output",
    wevents[-1]["type"] == "run.completed" and "1000" in out.replace(",", ""),
    out[:150],
)

# 6. Execution history + analytics
page = ok(c.get("/runs"))
check("run history lists runs", page["total"] >= 4, f"total={page['total']}")
summary = ok(c.get("/analytics/summary", params={"days": 1}))
check(
    "analytics from recorded runs",
    summary["runs"] == page["total"] and summary["tool_calls"] >= 2 and summary["input_tokens"] > 0,
    f"runs={summary['runs']} tools={summary['tool_calls']} tokens={summary['input_tokens']}/{summary['output_tokens']} p95={summary['p95_duration_ms']}ms",
)
timeline = ok(c.get(f"/runs/{run['id']}/events"))
check("run timeline persisted", len(timeline) == len(wevents), f"{len(timeline)} events")

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
