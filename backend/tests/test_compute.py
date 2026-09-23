"""compute: sandboxed arithmetic for derived figures."""

import json

import pytest

from app.agent.compute import compute

pytestmark = pytest.mark.asyncio


def _parse(out: str) -> dict:
    return json.loads(out)


async def test_arithmetic():
    out = _parse(await compute.ainvoke({"expression": "(17800 - 15300) / 15300"}))
    assert out["result"] == pytest.approx(0.1634, abs=1e-3)


async def test_helpers_over_data_param():
    out = _parse(await compute.ainvoke({
        "expression": "mean(pluck(data, 'pe'))",
        "data": [{"pe": 10}, {"pe": 14}, {"symbol": "X"}],  # missing key skipped
    }))
    assert out["result"] == 12


async def test_comprehension_and_lambda():
    out = _parse(await compute.ainvoke({
        "expression": "[v * 2 for v in data if v > 1]", "data": [1, 2, 3]
    }))
    assert out["result"] == [4, 6]
    out = _parse(await compute.ainvoke(
        {"expression": "sorted([3, 1, 2], key=lambda x: -x)"}))
    assert out["result"] == [3, 2, 1]


async def test_rejects_attributes_imports_and_unknown_names():
    for expr in [
        "().__class__",
        "data.__dict__",
        "'x'.upper()",
        "open('f')",
        "__import__('os')",
        "undefined_thing + 1",
    ]:
        out = _parse(await compute.ainvoke({"expression": expr}))
        assert "error" in out, expr


async def test_rejects_bad_syntax_and_giant_expr():
    out = _parse(await compute.ainvoke({"expression": "1 +* 2"}))
    assert "error" in out
    out = _parse(await compute.ainvoke({"expression": "1+" * 5000}))
    assert "error" in out
