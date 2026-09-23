"""End-to-end graph turn: START → context_manager → router → agent → END."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import context, nodes
from app.agent.graph import build_graph
from app.sectors import client

pytestmark = pytest.mark.asyncio


async def _no_jev(state, questions):
    return None


async def test_graph_turn_produces_ai_message(monkeypatch):
    monkeypatch.setattr(context, "jev_ask", _no_jev)
    monkeypatch.setattr(
        context, "recall_memories", AsyncMock(return_value="")
    )
    monkeypatch.setitem(
        nodes._LLM_BY_WORKFLOW,
        "general",
        SimpleNamespace(
            ainvoke=AsyncMock(return_value=AIMessage(content="Halo! Ada yang bisa dibantu?"))
        ),
    )

    graph = build_graph().compile()
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="halo")],
            "summary": "",
            "summarized_upto": 0,
            "workflow": "",
            "recalled_memories": "",
            "related_threads": "",
        },
        config={"configurable": {"user_id": 1}},  # no db → recall skipped
    )

    assert result["workflow"] == "general"
    last = result["messages"][-1]
    assert isinstance(last, AIMessage)
    assert last.content == "Halo! Ada yang bisa dibantu?"
    assert len(result["messages"]) == 2  # human + ai, nothing trimmed


async def test_graph_tool_call_executes_sectors_tool(
    monkeypatch, db, bound_session_maker
):
    monkeypatch.setattr(context, "jev_ask", _no_jev)
    monkeypatch.setattr(
        context, "recall_memories", AsyncMock(return_value="")
    )
    calls = []

    async def fake_get(path, params=None):
        calls.append((path, params))
        return 200, {"sectors": [{"banks": "Financials"}]}

    monkeypatch.setattr(client, "get", fake_get)
    monkeypatch.setitem(
        nodes._LLM_BY_WORKFLOW,
        "general",
        SimpleNamespace(
            ainvoke=AsyncMock(
                side_effect=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "sectors_list_subsectors",
                                "args": {},
                                "id": "call-1",
                                "type": "tool_call",
                            }
                        ],
                    ),
                    AIMessage(content="IDX subsectors: banks → Financials."),
                ]
            )
        ),
    )

    graph = build_graph().compile()
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="list IDX subsectors")],
            "summary": "",
            "summarized_upto": 0,
            "workflow": "",
            "recalled_memories": "",
            "related_threads": "",
        },
        config={"configurable": {"user_id": 1}},
    )

    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    envelope = json.loads(tool_msgs[0].content)
    assert envelope["status"] == 200
    assert envelope["data"] == {"sectors": [{"banks": "Financials"}]}
    assert calls == [("/v2/subsectors/", {})]
    last = result["messages"][-1]
    assert isinstance(last, AIMessage) and "banks" in last.content
