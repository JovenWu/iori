"""Agent node: the router's workflow picks the bound toolset."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent import nodes


def _state(workflow: str):
    return {
        "messages": [HumanMessage(content="hi")],
        "summarized_upto": 0,
        "workflow": workflow,
        "summary": "",
        "recalled_memories": "",
        "related_threads": "",
    }


@pytest.mark.asyncio
async def test_general_workflow_uses_toolless_llm(monkeypatch):
    toolless = SimpleNamespace(
        ainvoke=AsyncMock(return_value=AIMessage(content="hi"))
    )
    toolful = SimpleNamespace(
        ainvoke=AsyncMock(return_value=AIMessage(content="data"))
    )
    monkeypatch.setitem(nodes._LLM_BY_WORKFLOW, "general", toolless)
    monkeypatch.setattr(nodes, "agent_llm", toolful)

    await nodes.agent(_state("general"), {})

    toolless.ainvoke.assert_awaited_once()
    toolful.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_data_and_unknown_workflows_use_full_toolset(monkeypatch):
    toolless = SimpleNamespace(
        ainvoke=AsyncMock(return_value=AIMessage(content="hi"))
    )
    toolful = SimpleNamespace(
        ainvoke=AsyncMock(return_value=AIMessage(content="data"))
    )
    monkeypatch.setitem(nodes._LLM_BY_WORKFLOW, "general", toolless)
    monkeypatch.setattr(nodes, "agent_llm", toolful)

    for wf in ("sectors_data", "deep_research", "bogus", ""):
        await nodes.agent(_state(wf), {})

    assert toolful.ainvoke.await_count == 4
    toolless.ainvoke.assert_not_awaited()


def test_compose_system_honours_reply_language_setting():
    state = _state("")
    id_prompt = nodes._compose_system(state, {"configurable": {"lang": "id"}})
    assert "Bahasa Indonesia" in id_prompt
    en_prompt = nodes._compose_system(state, {"configurable": {"lang": "en"}})
    assert "English" in en_prompt
    default_prompt = nodes._compose_system(state, {"configurable": {}})
    assert "English" in default_prompt


def test_general_runnable_is_unbound_and_toolset_includes_new_tools():
    # `general` must never see tool schemas — the runnable is the bare model.
    assert nodes._LLM_BY_WORKFLOW["general"] is nodes._agent_base
    names = {t.name for t in nodes.AGENT_TOOLS}
    assert "sectors_compare" in names
    assert "sectors_index_daily" in names
    assert "compute" in names
