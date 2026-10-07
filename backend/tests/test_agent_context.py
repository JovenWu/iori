"""Context manager: token counting, summary boundary, JEV gates, injection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent import context
from app.core.config import settings


def _msgs(pairs: int):
    out = []
    for i in range(pairs):
        out += [HumanMessage(content=f"q{i}"), AIMessage(content=f"a{i}")]
    return out


def test_find_summary_boundary_keeps_last_turns():
    msgs = _msgs(3)  # human idx 0, 2, 4
    assert context._find_summary_boundary(msgs, 0, keep_turns=2) == 2
    assert context._find_summary_boundary(msgs, 0, keep_turns=1) == 4
    # Nothing new past summarized_upto → no boundary.
    assert context._find_summary_boundary(msgs, 2, keep_turns=2) is None
    # Fewer human turns than keep → nothing to fold.
    assert context._find_summary_boundary(_msgs(1), 0, keep_turns=2) is None


def test_messages_tokens_counts_content():
    msgs = [HumanMessage(content="hello world"), AIMessage(content="hi")]
    assert context.messages_tokens(msgs) > 2  # content + per-message overhead


@pytest.mark.asyncio
async def test_gates_fallback_when_jev_down(monkeypatch):
    async def no_jev(state, questions):
        return None

    monkeypatch.setattr(context, "jev_ask", no_jev)
    needs_memory, needs_threads = await context._context_gates("halo", "", "")
    assert needs_memory is True
    assert needs_threads is False


@pytest.mark.asyncio
async def test_gates_read_noul_answers(monkeypatch):
    async def fake_ask(state, questions):
        return SimpleNamespace(
            nouls={
                "needs_user_memory": SimpleNamespace(noul=0.9),
                "needs_past_chats": SimpleNamespace(noul=0.1),
            }
        )

    monkeypatch.setattr(context, "jev_ask", fake_ask)
    assert await context._context_gates("what was my name again?", "", "") == (
        True,
        False,
    )


@pytest.mark.asyncio
async def test_context_manager_injects_recalled_blocks(monkeypatch):
    async def fake_ask(state, questions):
        return SimpleNamespace(
            nouls={
                "needs_user_memory": SimpleNamespace(noul=0.9),
                "needs_past_chats": SimpleNamespace(noul=0.9),
            }
        )

    monkeypatch.setattr(context, "jev_ask", fake_ask)
    monkeypatch.setattr(
        context, "recall_memories", AsyncMock(return_value="[LONG-TERM MEMORIES]")
    )
    monkeypatch.setattr(
        context, "get_related_threads", AsyncMock(return_value=["d1"])
    )
    monkeypatch.setattr(
        context, "format_thread_signal", lambda ds: "Related past chats:\n- t"
    )

    updates = await context.context_manager(
        {
            "messages": [HumanMessage(content="what did we discuss before?")],
            "summary": "",
            "summarized_upto": 0,
        },
        {"configurable": {"db": object(), "user_id": 1, "thread_id": "t1"}},
    )
    assert updates["recalled_memories"] == "[LONG-TERM MEMORIES]"
    assert updates["related_threads"].startswith("Related past chats:")


@pytest.mark.asyncio
async def test_context_manager_skips_recall_without_db(monkeypatch):
    called = []

    async def track(state, questions):
        called.append(questions)
        return None

    monkeypatch.setattr(context, "jev_ask", track)
    spy = AsyncMock(return_value="x")
    monkeypatch.setattr(context, "recall_memories", spy)

    updates = await context.context_manager(
        {"messages": [HumanMessage(content="hi")], "summary": "", "summarized_upto": 0},
        {"configurable": {}},
    )
    assert updates == {"recalled_memories": "", "related_threads": ""}
    spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_manager_clears_stale_recall(monkeypatch):
    """A gated-off turn must not inherit last turn's recalled blocks — they
    persist in checkpoint state, so an explicit clear is required."""
    async def no_memory(state, questions):
        return SimpleNamespace(
            nouls={
                "needs_user_memory": SimpleNamespace(noul=0.1),
                "needs_past_chats": SimpleNamespace(noul=0.1),
            }
        )

    monkeypatch.setattr(context, "jev_ask", no_memory)
    spy = AsyncMock(return_value="[LONG-TERM MEMORIES]")
    monkeypatch.setattr(context, "recall_memories", spy)

    updates = await context.context_manager(
        {
            "messages": [HumanMessage(content="ok thanks")],
            "summary": "",
            "summarized_upto": 0,
            "recalled_memories": "[LONG-TERM MEMORIES]\n- stale\n[/]",
            "related_threads": "Related past chats:\n- old",
        },
        {"configurable": {"db": object(), "user_id": 1, "thread_id": "t1"}},
    )
    assert updates["recalled_memories"] == ""
    assert updates["related_threads"] == ""
    spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_manager_summarizes_over_limit(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_TOKEN_LIMIT", 0)
    monkeypatch.setattr(
        context, "_summarize", AsyncMock(return_value="folded summary")
    )

    async def no_jev(state, questions):
        return None

    monkeypatch.setattr(context, "jev_ask", no_jev)
    monkeypatch.setattr(
        context, "recall_memories", AsyncMock(return_value="")
    )

    updates = await context.context_manager(
        {
            "messages": _msgs(3),
            "summary": "",
            "summarized_upto": 0,
        },
        {"configurable": {}},
    )
    # KEEP_TURNS=2 → boundary at index 2; turns 0-1 folded into summary.
    assert updates["summarized_upto"] == 2
    assert updates["summary"] == "folded summary"
