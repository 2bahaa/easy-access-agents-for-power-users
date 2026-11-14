import pytest

from app.tools.calculator import CalculatorTool
from app.tools.registry import (
    ToolConfigError,
    ToolRegistry,
    UnknownToolError,
    build_default_registry,
)


def test_default_registry_contents() -> None:
    registry = build_default_registry()
    assert [t.name for t in registry.all()] == ["calculator", "file_reader"]
    assert "calculator" in registry and "shell" not in registry


def test_duplicate_registration_fails() -> None:
    registry = ToolRegistry([CalculatorTool()])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(CalculatorTool())


def test_unknown_tool() -> None:
    with pytest.raises(UnknownToolError):
        build_default_registry().get("shell")


def test_normalize_config() -> None:
    registry = build_default_registry()
    assert registry.normalize_config("calculator", {}) == {}
    assert registry.normalize_config("file_reader", {}) == {"subdir": ""}
    assert registry.normalize_config("file_reader", {"subdir": "notes/"}) == {"subdir": "notes"}
    with pytest.raises(ToolConfigError, match="subdir"):
        registry.normalize_config("file_reader", {"subdir": "../etc"})
    with pytest.raises(ToolConfigError, match="calculator"):
        registry.normalize_config("calculator", {"unexpected": 1})


def test_function_schemas_only_for_requested_tools() -> None:
    schemas = build_default_registry().function_schemas(["file_reader"])
    assert [s["function"]["name"] for s in schemas] == ["file_reader"]
