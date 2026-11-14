from pathlib import Path

import pytest
from pydantic import ValidationError

from app.tools.base import EmptyConfig, ToolContext, ToolError
from app.tools.calculator import CalculatorArgs, CalculatorTool, evaluate, format_number


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("17.5 * 23 + 4", "406.5"),
        ("2 * (3 + 4)", "14"),
        ("-3 + +5", "2"),
        ("7 / 2", "3.5"),
        ("7 // 2", "3"),
        ("7 % 3", "1"),
        ("2 ** 10", "1024"),
        ("2 ** -1", "0.5"),
        ("2 ** 3 ** 2", "512"),
        ("0.1 + 0.2", "0.30000000000000004"),
        ("  10 / 4  ", "2.5"),
        ("1e3", "1000"),
    ],
)
def test_valid_expressions(expression: str, expected: str) -> None:
    assert format_number(evaluate(expression)) == expected


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        # Code-injection attempts: names, calls, attributes, containers, lambdas.
        ("__import__('os').system('dir')", "Unsupported syntax"),
        ("open('x')", "Unsupported syntax"),
        ("x + 1", "Unsupported syntax"),
        ("(1).__class__", "Unsupported syntax"),
        ("[1, 2]", "Unsupported syntax"),
        ("lambda: 1", "Unsupported syntax"),
        ("1 if 1 else 2", "Unsupported syntax"),
        ("1 < 2", "Unsupported syntax"),
        ("'a' * 3", "Unsupported value"),
        ("True + 1", "Unsupported value"),
        ("1j * 2", "Unsupported value"),
        ("import os", "Invalid arithmetic expression"),
        ("1 +", "Invalid arithmetic expression"),
        ("", "Invalid arithmetic expression"),
        # Resource exhaustion and invalid math.
        ("9 ** 9 ** 9", "Exponent too large"),
        ("10 ** 101", "Exponent too large"),
        ("99 ** 99 * 99 ** 99", "too large"),
        ("1e308 * 10", "too large"),  # rejected by magnitude cap before it can overflow
        ("1 / 0", "Division by zero"),
        ("1 % 0", "Division by zero"),
        ("+".join(["1"] * 60), "too complex"),
    ],
)
def test_rejected_expressions(expression: str, message: str) -> None:
    with pytest.raises(ToolError, match=message):
        evaluate(expression)


def test_args_length_limit() -> None:
    with pytest.raises(ValidationError):
        CalculatorArgs(expression="1+" * 150 + "1")
    with pytest.raises(ValidationError):
        CalculatorArgs.model_validate({"expression": "1", "extra": True})


async def test_tool_run(tmp_path: Path) -> None:
    tool = CalculatorTool()
    args = tool.parse_args({"expression": "17.5 * 23 + 4"})
    result = await tool.run(args, EmptyConfig(), ToolContext(workspace_dir=tmp_path))
    assert result == "406.5"


def test_function_schema() -> None:
    schema = CalculatorTool().to_function_schema()
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "calculator"
    assert fn["parameters"]["required"] == ["expression"]
    assert fn["parameters"]["properties"]["expression"]["type"] == "string"
