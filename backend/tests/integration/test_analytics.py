"""Execution history and analytics: real numbers from recorded runs, workspace-scoped."""

import json
import logging

from httpx import AsyncClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability import JsonFormatter, current_run_id
from tests.conftest import UserClientFactory
from tests.fakes import FakeProvider, reply, tool_call
from tests.sse_helpers import create_agent, create_conversation, send_message


async def _chat(client: AsyncClient, fake_provider: FakeProvider) -> dict[str, str]:
    agent = await create_agent(client, name="Calc")
    conv = await create_conversation(client, agent["id"])
    fake_provider.model.responses = [
        reply("", tool_call("calculator", {"expression": "6*7"})),
        reply("42"),
    ]
    await send_message(client, conv["id"], "six times seven?")
    fake_provider.model.responses = [
        reply("", tool_call("calculator", {"expression": "1/0"})),
        reply("no"),
    ]
    await send_message(client, conv["id"], "divide by zero")
    return agent


async def test_run_history_and_summary(
    client: AsyncClient, fake_provider: FakeProvider, make_client: UserClientFactory
) -> None:
    agent = await _chat(client, fake_provider)

    page = (await client.get("/api/runs")).json()
    assert page["total"] == 2 and len(page["items"]) == 2
    assert all(r["agent_name"] == "Calc" and r["status"] == "completed" for r in page["items"])
    assert (await client.get("/api/runs", params={"status": "failed"})).json()["total"] == 0
    assert (await client.get("/api/runs", params={"kind": "workflow"})).json()["total"] == 0
    one = (await client.get("/api/runs", params={"limit": 1, "offset": 1})).json()
    assert one["total"] == 2 and len(one["items"]) == 1
    assert (await client.get("/api/runs", params={"kind": "bogus"})).status_code == 422

    s = (await client.get("/api/analytics/summary", params={"days": 7})).json()
    assert s["runs"] == 2 and s["by_status"] == {"completed": 2} and s["by_kind"] == {"agent": 2}
    assert s["success_rate"] == 1.0
    assert s["tool_calls"] == 2
    # Two model calls per run, each reporting 10 input / 5 output tokens (fake provider).
    assert (s["input_tokens"], s["output_tokens"], s["runs_without_usage"]) == (40, 20, 0)
    assert s["avg_duration_ms"] is not None and s["p95_duration_ms"] is not None
    assert len(s["daily"]) == 7 and s["daily"][-1]["runs"] == 2 and s["daily"][-1]["tokens"] == 60
    assert sum(d["runs"] for d in s["daily"][:-1]) == 0  # quiet days are zero, not invented
    assert s["top_agents"] == [{"agent_id": agent["id"], "name": "Calc", "runs": 2, "failed": 0}]
    calc = s["top_tools"][0]
    assert calc["tool"] == "calculator" and calc["calls"] == 2 and calc["failed"] == 1

    # Another tenant sees nothing.
    other = await make_client("other@example.com")
    assert (await other.get("/api/runs")).json()["total"] == 0
    empty = (await other.get("/api/analytics/summary")).json()
    assert empty["runs"] == 0 and empty["success_rate"] is None and empty["avg_duration_ms"] is None
    assert (await other.get("/api/runs", params={"agent_id": agent["id"]})).json()["total"] == 0


async def test_runs_are_traced(client: AsyncClient, fake_provider: FakeProvider) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # The module-level tracer is a ProxyTracer: it follows the global provider once set.
    trace.set_tracer_provider(provider)
    await _chat(client, fake_provider)
    spans = exporter.get_finished_spans()
    runs = [s for s in spans if s.name == "run.agent"]
    tools = [s for s in spans if s.name == "tool.call"]
    assert len(runs) == 2 and len(tools) == 2
    assert all(
        t.parent is not None and t.parent.span_id in {r.context.span_id for r in runs}
        for t in tools
    )
    kinds = [t.attributes.get("tool.error_kind") for t in tools]
    assert kinds.count(None) == 1  # 6*7 succeeded; 1/0 recorded its failure kind


def test_json_logs_carry_run_context() -> None:
    record = logging.LogRecord("app.x", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    token = current_run_id.set("run-123")
    try:
        data = json.loads(JsonFormatter().format(record))
    finally:
        current_run_id.reset(token)
    assert data["message"] == "hello world" and data["run_id"] == "run-123"
    assert data["level"] == "INFO" and "ts" in data
