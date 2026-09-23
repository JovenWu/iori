"""`compute` — sandboxed arithmetic for the agent.

LLMs are unreliable at mental math; for derived figures (growth %, spreads,
averages across rows it just fetched) the model writes a small Python
expression instead of guessing. The expression is AST-whitelisted — literals,
operators, comprehensions, lambdas, and a fixed set of numeric helpers. No
attribute access (blocks dunder escapes and method calls — use `get` and
subscripting), no statements, no imports, and every name resolves inside the
provided env only.
"""

import ast
import json
import math
import statistics
from typing import Any

from langchain_core.tools import tool

_MAX_EXPR_CHARS = 2000
_MAX_RESULT_CHARS = 8000


def _pluck(rows: Any, key: str) -> list:
    """[{k: v}, ...] → [v], skipping rows without a non-null value."""
    if not isinstance(rows, list):
        return []
    return [r[key] for r in rows if isinstance(r, dict) and r.get(key) is not None]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else default


_ENV = {
    # builtins — numeric/collection only, no I/O or introspection
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "filter": filter, "float": float, "int": int,
    "len": len, "list": list, "map": map, "max": max, "min": min,
    "range": range, "reversed": reversed, "round": round, "set": set,
    "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    # statistics
    "mean": statistics.mean, "median": statistics.median,
    "pstdev": statistics.pstdev, "stdev": statistics.stdev,
    "variance": statistics.variance,
    # math
    "ceil": math.ceil, "exp": math.exp, "floor": math.floor,
    "log": math.log, "log10": math.log10, "pow": pow, "sqrt": math.sqrt,
    # helpers
    "get": _get, "pluck": _pluck,
    # constants
    "pi": math.pi, "e": math.e,
}

_ALLOWED_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Store,
    ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Starred,
    ast.Subscript, ast.Slice,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Call, ast.keyword,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
    ast.comprehension, ast.Lambda, ast.arguments, ast.arg,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.Is, ast.IsNot,
)


@tool
async def compute(expression: str, data: Any = None) -> str:
    """Evaluate a small Python arithmetic expression and return the result —
    use for every derived figure (growth %, spreads, averages, ratios across
    tickers) instead of doing mental math. `data` optionally carries a JSON
    value from a previous tool result. Helpers include get(d, key),
    pluck(rows, key), mean, median, stdev, sum, min, max, sorted, round.
    No attribute access — index dicts with ["key"], not .key.

    Args:
        expression: Python expression, e.g. "(new - old) / old * 100".
        data: Optional JSON value available as `data` in the expression.
    """
    expr = expression.strip()
    if not expr or len(expr) > _MAX_EXPR_CHARS:
        return json.dumps({"error": "invalid_expression"})
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        return json.dumps({"error": f"syntax: {exc.msg}"})
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return json.dumps({"error": f"disallowed: {type(node).__name__}"})
    if isinstance(data, str):  # models may hand back a raw envelope string
        try:
            data = json.loads(data)
        except ValueError:
            pass
    env = {**_ENV, "data": data, "__builtins__": {}}
    try:
        result = eval(compile(tree, "<compute>", "eval"), env)  # noqa: S307
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
    try:
        json.dumps(result)
    except (TypeError, ValueError):
        return json.dumps({"error": "result_not_json"})
    out = json.dumps({"result": result}, default=str)
    if len(out) > _MAX_RESULT_CHARS:
        out = json.dumps(
            {"result": out[:_MAX_RESULT_CHARS] + "…", "truncated": True}
        )
    return out
