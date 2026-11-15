"""Safe templating and condition expressions (no eval/exec, whitelisted AST only).

Templates: `{{ node_id }}` inserts a node's output, `{{ input.name }}` a workflow input.

Conditions: Python-like boolean expressions over node outputs and inputs, e.g.
    contains(classify, "urgent") and len(summary) > 100
    input_priority == "high" or number(score) >= 7
Allowed: and/or/not, comparisons, string/number/bool constants, names (node ids and
`input_<name>`), and the functions contains, startswith, endswith, len, lower, upper,
number. Nothing else parses.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Any

from app.runtime.workflow.spec import TEMPLATE_REF

MAX_EXPR_NODES = 60


class ExpressionError(ValueError):
    pass


def render(template: str, outputs: dict[str, str], inputs: dict[str, str]) -> str:
    def sub(m: Any) -> str:
        head, attr = m.group(1), m.group(2)
        if head == "input":
            return inputs.get(attr or "", "")
        return outputs.get(head, "")

    return TEMPLATE_REF.sub(sub, template)


def _number(value: Any) -> float:
    try:
        return float(str(value).strip())
    except ValueError:
        raise ExpressionError(f"'{str(value)[:30]}' is not a number") from None


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "contains": lambda haystack, needle: str(needle).lower() in str(haystack).lower(),
    "startswith": lambda s, p: str(s).strip().lower().startswith(str(p).lower()),
    "endswith": lambda s, p: str(s).strip().lower().endswith(str(p).lower()),
    "len": lambda s: len(str(s)),
    "lower": lambda s: str(s).lower(),
    "upper": lambda s: str(s).upper(),
    "number": _number,
}
COMPARE: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}


def parse_condition(expression: str) -> ast.Expression:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"Invalid expression: {e.msg}") from None
    count = 0
    for node in ast.walk(tree):
        count += 1
        if count > MAX_EXPR_NODES:
            raise ExpressionError("Expression is too long")
        allowed = (
            ast.Expression,
            ast.BoolOp,
            ast.And,
            ast.Or,
            ast.UnaryOp,
            ast.Not,
            ast.Compare,
            ast.Name,
            ast.Load,
            ast.Constant,
            ast.Call,
            *COMPARE,
        )
        if not isinstance(node, allowed):
            raise ExpressionError(f"'{type(node).__name__}' is not allowed in conditions")
        if isinstance(node, ast.Call):
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id not in FUNCTIONS
                or node.keywords
            ):
                raise ExpressionError(
                    "Only contains, startswith, endswith, len, lower, upper, number are allowed"
                )
        if isinstance(node, ast.Constant) and not isinstance(node.value, (str, int, float, bool)):
            raise ExpressionError("Only text, number and true/false constants are allowed")
    return tree


def condition_names(expression: str) -> set[str]:
    tree = parse_condition(expression)
    return {
        n.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id not in FUNCTIONS and n.id not in ("True", "False")
    }


def evaluate(expression: str, outputs: dict[str, str], inputs: dict[str, str]) -> bool:
    tree = parse_condition(expression)

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id.startswith("input_"):
                return inputs.get(node.id.removeprefix("input_"), "")
            return outputs.get(node.id, "")
        if isinstance(node, ast.BoolOp):
            values = [bool(ev(v)) for v in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp):
            return not bool(ev(node.operand))
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)
            return FUNCTIONS[node.func.id](*[ev(a) for a in node.args])
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, right_node in zip(node.ops, node.comparators, strict=True):
                right = ev(right_node)
                if isinstance(left, (int, float)) != isinstance(right, (int, float)):
                    left, right = str(left), str(right)  # compare mixed values as text
                try:
                    if not COMPARE[type(op)](left, right):
                        return False
                except TypeError:
                    raise ExpressionError("Cannot compare these values") from None
                left = right
            return True
        raise ExpressionError("Unsupported expression")  # pragma: no cover - parse guards

    try:
        return bool(ev(tree))
    except TypeError as e:
        raise ExpressionError(f"Wrong arguments: {e}") from None
