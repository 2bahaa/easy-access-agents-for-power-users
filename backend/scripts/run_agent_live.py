"""Manual check: run the real agent runtime against local Ollama and print the event stream.

Usage (from backend/):
    uv run python -m scripts.run_agent_live [model] ["question"]
"""

import asyncio
import sys
import uuid

from langchain_core.messages import HumanMessage

from app.config import get_settings
from app.runtime.executor import AgentRun
from app.runtime.providers.ollama import OllamaProvider
from app.runtime.types import AgentConfig, RunRequest, RuntimeCaps, ToolGrant
from app.tools.base import ToolContext
from app.tools.registry import build_default_registry


async def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "llama3.2:1b"
    question = sys.argv[2] if len(sys.argv) > 2 else "What is 17.5 * 23 + 4?"
    settings = get_settings()

    config = AgentConfig(
        agent_id=uuid.uuid4(),
        name="Live check",
        provider="ollama",
        model=model,
        model_params={"temperature": 0},
        system_prompt="You are a helpful assistant. Use tools when they help.",
        tools=[ToolGrant(name="calculator"), ToolGrant(name="file_reader")],
        max_tool_calls=4,
        run_timeout_s=120,
    )
    run = AgentRun(
        RunRequest(run_id=uuid.uuid4(), config=config, history=[HumanMessage(question)]),
        OllamaProvider(settings.ollama_base_url),
        build_default_registry(),
        RuntimeCaps(
            max_tool_calls=settings.max_tool_calls_cap,
            run_timeout_s=settings.run_timeout_cap_s,
            tool_timeout_s=settings.tool_timeout_s,
        ),
        ToolContext(workspace_dir=settings.workspace_dir),
    )

    deltas = 0
    async for event in run.stream():
        if event.type in ("message.delta", "reasoning.delta"):
            deltas += 1
            continue
        payload = event.model_dump(exclude={"run_id", "seq", "ts", "type"})
        print(f"{event.seq:>3} {event.type:<20} {payload}")
    print(
        f"\nstreamed {deltas} token deltas; status={run.result.status} "
        f"tool_calls={run.result.tool_call_count} usage={run.result.usage}"
    )


if __name__ == "__main__":
    asyncio.run(main())
