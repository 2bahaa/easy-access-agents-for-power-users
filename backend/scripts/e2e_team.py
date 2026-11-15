# ruff: noqa: E501  (manual verification script)
"""Live check of a supervisor team workflow (same spec shape as the Studio's team template).

Usage: uv run python scripts/e2e_team.py http://127.0.0.1:8000/api [model]
"""

import json
import sys
import time

import httpx

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002/api"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "qwen2.5:3b"
c = httpx.Client(base_url=API, timeout=1800)
tok = c.post(
    "/auth/register",
    json={"email": f"team{int(time.time())}@example.com", "password": "e2e-password-123"},
).json()
c.headers["Authorization"] = f"Bearer {tok['access_token']}"


def agent(name: str, prompt: str, tools: list[dict[str, str]]) -> str:
    a = c.post(
        "/agents",
        json={
            "name": name,
            "model": MODEL,
            "system_prompt": prompt,
            "tools": tools,
            "run_timeout_s": 600,
        },
    ).json()
    c.post(f"/agents/{a['id']}/publish", json={"note": ""})
    return str(a["id"])


calc = agent(
    "Calculator",
    "Use the calculator for every computation. Reply with the number only.",
    [{"name": "calculator"}],
)
writer = agent("Writer", "Write one short, friendly sentence.", [])
spec = {
    "schema_version": 1,
    "nodes": [
        {"id": "start", "type": "start", "config": {"inputs": [{"name": "task"}]}},
        {
            "id": "team",
            "type": "supervisor",
            "config": {
                "model": MODEL,
                "task": "{{ input.task }}",
                "members": [
                    {"name": "calculator", "agent_id": calc, "role": "exact arithmetic"},
                    {"name": "writer", "agent_id": writer, "role": "writes friendly sentences"},
                ],
                "max_delegations": 4,
            },
        },
        {"id": "end", "type": "end", "config": {"output": "{{ team }}"}},
    ],
    "edges": [{"source": "start", "target": "team"}, {"source": "team", "target": "end"}],
}
v = c.post("/workflows/validate", json=spec).json()
assert v["valid"], v
wf = c.post("/workflows", json={"name": "Team", "spec": spec}).json()
run = c.post(
    f"/workflows/{wf['id']}/runs",
    json={
        "inputs": {
            "task": "Compute 37 * 43 with the calculator member, then have the writer announce the result."
        }
    },
).json()
events = []
for block in c.get(f"/runs/{run['id']}/stream").text.split("\n\n"):
    data = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
    if data:
        events.append(json.loads("\n".join(data)))
for e in events:
    if e["type"] in (
        "agent.delegated",
        "agent.result",
        "node.failed",
        "run.completed",
        "run.failed",
    ):
        print(
            e["type"],
            {k: e.get(k) for k in ("member", "reason", "task", "output", "ok", "error", "message")},
        )
delegated = [e for e in events if e["type"] == "agent.delegated"]
ok = (
    events[-1]["type"] == "run.completed"
    and bool(delegated)
    and all(e.get("ok") for e in events if e["type"] == "agent.result")
)
print(
    "TEAM",
    "PASS" if ok else "FAIL",
    f"{len(delegated)} delegation(s); output: {events[-1].get('output', '')[:200]}",
)
sys.exit(0 if ok else 1)
