"""Block-list message content — reasoning-capable models stream typed blocks
({"type": "reasoning"|"text"|...}) instead of a plain string, so consumers
read the pieces they need via app.agent.messages helpers."""

import pytest
from unittest.mock import AsyncMock
from langchain_core.messages import AIMessageChunk

from app.agent.messages import message_reasoning, message_text
from app.agent.runs import AgentRun

_REASONING_CHUNK = [
    {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [{"type": "summary_text", "text": "thinking about "}],
    }
]
_TEXT_CHUNK = [{"type": "text", "text": "The answer"}]


def test_message_text_plain_string():
    assert message_text("hello") == "hello"
    assert message_reasoning("hello") == ""


def test_message_text_blocks():
    content = [*_REASONING_CHUNK, *_TEXT_CHUNK]
    assert message_text(content) == "The answer"


def test_message_reasoning_blocks():
    content = [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "a"}]},
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "b"}]},
        *_TEXT_CHUNK,
    ]
    assert message_reasoning(content) == "ab"


def test_message_reasoning_edge_shapes():
    assert message_reasoning([{"type": "reasoning"}]) == ""
    assert message_reasoning([{"type": "reasoning", "summary": []}]) == ""
    assert message_reasoning([]) == ""


@pytest.mark.asyncio
async def test_run_turn_emits_reasoning_before_tokens(monkeypatch):
    """Agent-node chunks with reasoning blocks emit `reasoning` events ahead
    of `token` events; neither is folded into the other's text."""
    from app.agent import service

    chunks = [
        AIMessageChunk(content=_REASONING_CHUNK),
        AIMessageChunk(
            content=[
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "flow"}],
                }
            ]
        ),
        AIMessageChunk(content=_TEXT_CHUNK),
        AIMessageChunk(content=[{"type": "text", "text": " is 42"}]),
    ]
    meta = {"langgraph_node": "agent"}

    class FakeGraph:
        async def astream(self, *args, **kwargs):
            for c in chunks:
                yield "messages", (c, meta)
            yield "updates", {
                "agent": {"messages": []},
            }

    monkeypatch.setattr(service, "_graph", FakeGraph())
    monkeypatch.setattr(service, "_ensure_title", AsyncMock())
    monkeypatch.setattr(service, "_post_turn", AsyncMock())

    run = AgentRun("thread-r", 1)
    await service.run_turn(run, 1, "thread-r", "hi")

    types = [e["type"] for _, e in run._buffer]
    assert types == ["reasoning", "reasoning", "token", "token", "done"]
    datas = [e["data"] for _, e in run._buffer]
    assert "".join(datas[:2]) == "thinking about flow"
    assert datas[-1]["answer"] == "The answer is 42"


@pytest.mark.asyncio
async def test_run_turn_plain_chunks_emit_no_reasoning(monkeypatch):
    """Models without reasoning behave exactly as before."""
    from app.agent import service

    class FakeGraph:
        async def astream(self, *args, **kwargs):
            yield "messages", (
                AIMessageChunk(content="plain"),
                {"langgraph_node": "agent"},
            )
            yield "updates", {}

    monkeypatch.setattr(service, "_graph", FakeGraph())
    monkeypatch.setattr(service, "_ensure_title", AsyncMock())
    monkeypatch.setattr(service, "_post_turn", AsyncMock())

    run = AgentRun("thread-r2", 1)
    await service.run_turn(run, 1, "thread-r2", "hi")

    assert [e["type"] for _, e in run._buffer] == ["token", "done"]
