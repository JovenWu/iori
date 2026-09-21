"""End-to-end graph turn: START → context_manager → router → agent → END."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent import context, nodes
from app.agent.graph import build_graph


@pytest.mark.asyncio
async def test_graph_turn_produces_ai_message(monkeypatch):
    async def no_jev(state, questions):
        return None

    monkeypatch.setattr(context, "jev_ask", no_jev)
    monkeypatch.setattr(
        context, "recall_memories", AsyncMock(return_value="")
    )
    monkeypatch.setattr(
        nodes,
        "agent_llm",
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
