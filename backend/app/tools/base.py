"""Tool contract.

A tool is trusted code. What an agent may do with it is decided by per-agent
permission (agent_tools rows) and per-agent config validated by `config_model`.
The runtime validates model-provided arguments with `args_model` before `run`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict


class ToolError(Exception):
    """Expected, user-safe tool failure. The message is shown to the model and the user,
    so it must never contain stack traces or absolute host paths."""


class EmptyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolContext:
    workspace_dir: Path


class Tool[ArgsT: BaseModel, ConfigT: BaseModel](ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    args_model: type[ArgsT]
    config_model: type[ConfigT]
    timeout_s: float | None = None  # None -> settings.tool_timeout_s

    @abstractmethod
    async def run(self, args: ArgsT, config: ConfigT, ctx: ToolContext) -> str: ...

    def parse_args(self, raw: dict[str, Any]) -> ArgsT:
        return self.args_model.model_validate(raw)

    def parse_config(self, raw: dict[str, Any]) -> ConfigT:
        return self.config_model.model_validate(raw)

    def args_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()

    def config_schema(self) -> dict[str, Any]:
        return self.config_model.model_json_schema()

    def to_function_schema(self) -> dict[str, Any]:
        """OpenAI-style function schema, accepted by Ollama and LangChain `bind_tools`."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema(),
            },
        }


AnyTool = Tool[Any, Any]
