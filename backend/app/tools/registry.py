"""Registry of tools available to a run: the code-defined tools, extended per run with the
agent's runtime-defined tools (MCP, custom HTTP)."""

from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.tools.base import ToolLike


class UnknownToolError(KeyError):
    pass


class ToolConfigError(ValueError):
    pass


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolLike] = ()) -> None:
        self._tools: dict[str, ToolLike] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolLike) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolLike:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownToolError(name) from None

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def all(self) -> list[ToolLike]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    def extended(self, extra: Iterable[ToolLike]) -> "ToolRegistry":
        """A new registry with these tools added (the shared registry is never mutated)."""
        return ToolRegistry([*self._tools.values(), *extra])

    def normalize_config(self, name: str, raw: dict[str, Any]) -> dict[str, Any]:
        """Validate a per-agent config and return its canonical form for storage."""
        tool = self.get(name)
        try:
            normalized: dict[str, Any] = tool.parse_config(raw).model_dump(mode="json")
            return normalized
        except ValidationError as e:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'config'}: {err['msg']}"
                for err in e.errors()
            )
            raise ToolConfigError(f"Invalid config for tool '{name}': {problems}") from e

    def function_schemas(self, names: Iterable[str]) -> list[dict[str, Any]]:
        """Schemas for the given (permitted) tools only."""
        return [self.get(n).to_function_schema() for n in names]


def build_default_registry() -> ToolRegistry:
    from app.tools.calculator import CalculatorTool
    from app.tools.file_reader import FileReaderTool

    return ToolRegistry([CalculatorTool(), FileReaderTool()])
