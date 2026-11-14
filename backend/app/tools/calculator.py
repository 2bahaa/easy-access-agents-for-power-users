"""Safe arithmetic calculator. Parses with `ast` and evaluates a strict whitelist — no eval()."""

import ast
import math
import operator
from collections.abc import Callable
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import EmptyConfig, Tool, ToolContext, ToolError

Number = int | float

MAX_EXPRESSION_LENGTH = 200
MAX_NODES = 100
MAX_EXPONENT = 100
MAX_MAGNITUDE = 10**100

_BIN_OPS: dict[type[ast.operator], Callable[[Number, Number], Number]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[Number], Number]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculatorArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(
        min_length=1,
        max_length=MAX_EXPRESSION_LENGTH,
        description="Arithmetic expression using numbers, + - * / // % ** and parentheses, "
        "e.g. '17.5 * 23 + 4'",
    )


def _check(value: Number) -> Number:
    if isinstance(value, float) and not math.isfinite(value):
        raise ToolError("Result is not a finite number")
    if abs(value) > MAX_MAGNITUDE:
        raise ToolError("Result is too large")
    return value


def _eval(node: ast.AST) -> Number:
    if isinstance(node, ast.Constant):
        # bool is a subclass of int: reject it explicitly. complex is not allowed.
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise ToolError(f"Unsupported value: {node.value!r}")
        return _check(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _check(_UNARY_OPS[type(node.op)](_eval(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ToolError(f"Exponent too large (max {MAX_EXPONENT})")
        try:
            return _check(_BIN_OPS[type(node.op)](left, right))
        except ZeroDivisionError:
            raise ToolError("Division by zero") from None
        except OverflowError:
            raise ToolError("Result is too large") from None
    raise ToolError(f"Unsupported syntax: {type(node).__name__}")


def evaluate(expression: str) -> Number:
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise ToolError("Invalid arithmetic expression") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ToolError("Expression is too complex")
    return _eval(tree.body)


def format_number(value: Number) -> str:
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


class CalculatorTool(Tool[CalculatorArgs, EmptyConfig]):
    name: ClassVar[str] = "calculator"
    description: ClassVar[str] = (
        "Evaluate an arithmetic expression exactly. Use this for any calculation instead of "
        "doing math yourself."
    )
    args_model = CalculatorArgs
    config_model = EmptyConfig
    timeout_s = 2.0

    async def run(self, args: CalculatorArgs, config: EmptyConfig, ctx: ToolContext) -> str:
        return format_number(evaluate(args.expression))
