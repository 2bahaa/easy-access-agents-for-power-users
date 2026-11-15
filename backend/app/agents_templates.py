"""Built-in agent templates (code-defined, like tools). They pre-fill the Agent Builder;
the user still chooses the model, so no capability is assumed."""

from app.schemas.agents import ModelParams, ToolSelection
from app.schemas.platform import AgentTemplate

TEMPLATES: list[AgentTemplate] = [
    AgentTemplate(
        id="research-assistant",
        name="Research assistant",
        description="Reads documents from the workspace and answers with references to them.",
        category="Knowledge",
        system_prompt=(
            "You are a careful research assistant. When a question concerns files in the "
            "workspace, read them with the file reader before answering. Quote the relevant "
            "passages and say which file they come from. If the files do not contain the "
            "answer, say so instead of guessing."
        ),
        tools=[ToolSelection(name="file_reader")],
        model_params=ModelParams(temperature=0.2),
        suggested_skills=["concise-answers"],
    ),
    AgentTemplate(
        id="calculator-helper",
        name="Calculation helper",
        description="Answers numeric questions exactly by using the calculator tool.",
        category="Productivity",
        system_prompt=(
            "You help with calculations. Always use the calculator tool for arithmetic instead "
            "of computing in your head, then explain the result in one or two sentences."
        ),
        tools=[ToolSelection(name="calculator")],
        model_params=ModelParams(temperature=0),
        max_tool_calls=6,
    ),
    AgentTemplate(
        id="concise-qa",
        name="Concise Q&A",
        description="General-purpose assistant that keeps answers short. No tools.",
        category="General",
        system_prompt="You are a helpful assistant. Answer directly and briefly.",
        model_params=ModelParams(temperature=0.5),
        suggested_skills=["concise-answers"],
    ),
    AgentTemplate(
        id="data-analyst",
        name="File & numbers analyst",
        description="Reads text/CSV files and computes figures from them with the calculator.",
        category="Knowledge",
        system_prompt=(
            "You analyse data files from the workspace. Read the file first, extract the numbers "
            "you need, and use the calculator for every computation. Show the figures you used."
        ),
        tools=[ToolSelection(name="file_reader"), ToolSelection(name="calculator")],
        model_params=ModelParams(temperature=0.1),
        max_tool_calls=12,
        run_timeout_s=240,
    ),
]

TEMPLATES_BY_ID = {t.id: t for t in TEMPLATES}
