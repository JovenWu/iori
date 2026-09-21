"""Memory write path: JEV dedup decisions, LLM fallback, hash dedup, apply."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.memory import pipeline, store
from app.models.memory import Memory


def _mem(content, id=None):
    return SimpleNamespace(id=id or uuid.uuid4(), content=content)


def _jev_response(choices):
    return SimpleNamespace(choices=choices, scores={}, nouls={})


async def _all_unrelated(state, questions):
    return _jev_response(
        {
            key: SimpleNamespace(choice="unrelated", confidence=0.9)
            for key in questions
        }
    )


@pytest.mark.asyncio
async def test_jev_decision_add_when_all_unrelated(monkeypatch):
    monkeypatch.setattr(pipeline, "jev_ask", _all_unrelated)
    action, target = await pipeline._decide_with_jev(
        "User likes tea", [_mem("User likes coffee")]
    )
    assert action == "ADD"
    assert target is None


@pytest.mark.asyncio
async def test_jev_decision_maps_relations(monkeypatch):
    target_mem = _mem("User is named Budi")
    for relation, expected in [
        ("restates", "NOOP"),
        ("refines", "UPDATE"),
        ("contradicts", "DELETE"),
    ]:

        async def fake_ask(state, questions, _rel=relation):
            return _jev_response(
                {"mem_0": SimpleNamespace(choice=_rel, confidence=0.95)}
            )

        monkeypatch.setattr(pipeline, "jev_ask", fake_ask)
        action, target = await pipeline._decide_with_jev("new fact", [target_mem])
        assert action == expected
        assert target is target_mem


@pytest.mark.asyncio
async def test_jev_decision_add_when_no_candidates():
    action, target = await pipeline._decide_with_jev("User likes coffee", [])
    assert action == "ADD"
    assert target is None


@pytest.mark.asyncio
async def test_jev_decision_none_when_unavailable(monkeypatch):
    async def no_jev(state, questions):
        return None

    monkeypatch.setattr(pipeline, "jev_ask", no_jev)
    assert await pipeline._decide_with_jev("f", [_mem("x")]) is None


@pytest.mark.asyncio
async def test_process_turn_stores_and_dedups_fact(db, user, monkeypatch):
    monkeypatch.setattr(store, "embed_text", AsyncMock(return_value=[0.1] * 1536))
    monkeypatch.setattr(
        pipeline,
        "extract_facts",
        AsyncMock(return_value=["User likes coffee"]),
    )
    monkeypatch.setattr(pipeline, "jev_ask", _all_unrelated)

    await pipeline.process_turn(
        user.id, None, "saya suka kopi sekali", "baik", "", [], db
    )
    rows = (
        (await db.execute(select(Memory).where(Memory.user_id == user.id)))
        .scalars()
        .all()
    )
    assert [r.content for r in rows] == ["User likes coffee"]

    # Same fact again → exact-hash dedup skips the whole decision path.
    await pipeline.process_turn(
        user.id, None, "saya suka kopi sekali", "baik", "", [], db
    )
    rows = (
        (await db.execute(select(Memory).where(Memory.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_process_turn_never_raises(db, user, monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "extract_facts",
        AsyncMock(side_effect=RuntimeError("extractor down")),
    )
    # Grab the id up front: process_turn's internal rollback expires `user`,
    # and touching user.id afterwards would lazy-load outside a greenlet.
    user_id = user.id
    await pipeline.process_turn(user_id, None, "saya suka kopi", "ok", "", [], db)
    assert await store.count_memories(db, user_id) == 0
