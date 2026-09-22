"""Tools node: ToolNode passthrough + chart judging per ToolMessage."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import tools_node

pytestmark = pytest.mark.asyncio


def _state_with_tool_call():
    return {
        "messages": [
            HumanMessage(content="harga BBCA"),
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "sectors_daily_prices",
                    "args": {"symbol": "BBCA"},
                    "id": "call-1",
                    "type": "tool_call",
                }],
            ),
        ],
        "charts": [],
    }


async def test_charts_appended_with_anchor(monkeypatch):
    spec = {"id": "x", "view": "price_volume", "kind": "price_volume",
            "title": "t", "x": {}, "series": [], "data": [],
            "fetched_at": "", "format": "number"}
    judge = AsyncMock(return_value=spec)
    monkeypatch.setattr(tools_node, "judge_and_extract", judge)

    async def fake_tool_node(state, config=None):
        return {
            "messages": [
                ToolMessage(content="{}", tool_call_id="call-1",
                            name="sectors_daily_prices")
            ]
        }

    monkeypatch.setattr(tools_node, "_tool_node",
                        SimpleNamespace(ainvoke=fake_tool_node))
    result = await tools_node.tools(_state_with_tool_call(), {})

    assert len(result["charts"]) == 1
    # anchor = index of the ToolMessage in the full history:
    # human(0), ai tool_call(1), tool(2)
    assert result["charts"][0]["anchor"] == 2
    judge.assert_awaited_once()
    assert judge.await_args.args[0] == "sectors_daily_prices"
    assert judge.await_args.args[2] == "harga BBCA"  # the question


async def test_no_spec_no_charts_key(monkeypatch):
    monkeypatch.setattr(tools_node, "judge_and_extract",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(
        tools_node, "_tool_node",
        SimpleNamespace(ainvoke=AsyncMock(return_value={
            "messages": [ToolMessage(content="{}", tool_call_id="c",
                                     name="sectors_news")]
        })),
    )
    result = await tools_node.tools(_state_with_tool_call(), {})
    assert "charts" not in result or result.get("charts") == []
