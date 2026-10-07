"""Hybrid recall units: RRF fusion, JEV rerank normalization, fallbacks."""

import uuid
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.memory import recall


def _cand(content, id=None):
    return SimpleNamespace(id=id or uuid.uuid4(), content=content)


def test_rrf_merge_fuses_both_lists():
    a, b, c = _cand("a"), _cand("b"), _cand("c")
    merged = recall.rrf_merge(
        semantic=[(a, 0.9), (b, 0.8)],
        bm25=[(b, 0.5), (c, 0.4)],
        k=60,
    )
    ids = [item.id for item, _ in merged]
    # b appears in both arms → fused score wins outright.
    assert ids[0] == b.id
    # a (semantic rank 1) edges c (bm25 rank 2).
    assert ids[1] == a.id
    assert set(ids) == {a.id, b.id, c.id}


def test_rerank_filter_threshold_and_cosine_rescue():
    cands = [(_cand("m1"), 0.5), (_cand("m2"), 0.5)]
    m1, m2 = cands[0][0], cands[1][0]
    cosine = {m1.id: 0.7, m2.id: 0.2}

    # Everything below the rerank threshold → strongest cosine hit ≥ floor rescued.
    ranked = recall._apply_rerank_filter(
        cands, {0: 0.1, 1: 0.1}, cosine, threshold=0.5, vector_floor=0.6
    )
    assert [r.memory.id for r in ranked] == [m1.id]

    # Nothing ≥ floor → empty.
    ranked = recall._apply_rerank_filter(
        cands,
        {0: 0.1, 1: 0.1},
        {m1.id: 0.3, m2.id: 0.2},
        threshold=0.5,
        vector_floor=0.6,
    )
    assert ranked == []


@pytest.mark.asyncio
async def test_jev_rerank_normalizes_scores(monkeypatch):
    cands = [(_cand("m1"), 0.8), (_cand("m2"), 0.7)]
    fake = SimpleNamespace(
        scores={
            "cand_0": SimpleNamespace(score=3.0),
            "cand_1": SimpleNamespace(score=0.0),
        }
    )

    async def fake_ask(state, questions):
        assert len(questions) == 2
        assert state["candidates"][0]["memory"] == "m1"
        return fake

    monkeypatch.setattr(recall, "jev_ask", fake_ask)
    scores = await recall._jev_rerank_scores("q", cands)
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_rerank_falls_back_to_llm(monkeypatch):
    cand = _cand("m1")

    async def no_jev(state, questions):
        return None

    async def fake_llm(query, candidates):
        return {0: 0.9}

    monkeypatch.setattr(recall, "jev_ask", no_jev)
    monkeypatch.setattr(recall, "_llm_rerank_scores", fake_llm)
    ranked = await recall.rerank_candidates("q", [(cand, 0.8)], {cand.id: 0.8})
    assert ranked[0].rerank_score == 0.9


@pytest.mark.asyncio
async def test_rerank_vector_order_last_resort(monkeypatch):
    weak, strong = _cand("weak"), _cand("strong")

    async def no_jev(state, questions):
        return None

    async def no_llm(query, candidates):
        return None

    monkeypatch.setattr(recall, "jev_ask", no_jev)
    monkeypatch.setattr(recall, "_llm_rerank_scores", no_llm)
    ranked = await recall.rerank_candidates("q", [(weak, 0.4), (strong, 0.9)])
    assert ranked[0].memory is strong


# ---------------------------------------------------------------------------
# Full-scan recall — JEV judges every memory, retrieval is fallback only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_judges_all_memories_skipping_retrieval(monkeypatch):
    """A memory retrieval could never surface still reaches the judge."""
    mems = [
        _cand("User prefers conservative dividend plays"),
        _cand("User asked about BAJA rights last week"),
    ]

    async def fake_list(db, user_id, limit=50, offset=0):
        return mems

    async def boom(db, user_id, query, top_k=10):
        raise AssertionError("retrieval must not run under the scan cap")

    async def fake_ask(state, questions):
        assert len(questions) == 2
        assert state["candidates"][0]["memory"].startswith("User prefers")
        return SimpleNamespace(
            scores={
                "cand_0": SimpleNamespace(score=3.0),
                "cand_1": SimpleNamespace(score=0.0),
            }
        )

    monkeypatch.setattr(recall.store, "list_memories", fake_list)
    monkeypatch.setattr(recall.store, "vector_search", boom)
    monkeypatch.setattr(recall.store, "bm25_search", boom)
    monkeypatch.setattr(recall, "jev_ask", fake_ask)

    out = await recall.recall_memories(None, 1, "should i exercise my BAJA rights")
    assert "conservative dividend" in out
    assert "asked about BAJA" not in out  # judged below threshold


@pytest.mark.asyncio
async def test_scan_returns_empty_when_nothing_relevant(monkeypatch):
    """The judge is the arbiter — no forced weak-vector rescue."""
    mems = [_cand("likes spicy food"), _cand("birthday in march")]

    async def fake_list(db, user_id, limit=50, offset=0):
        return mems

    async def fake_ask(state, questions):
        return SimpleNamespace(
            scores={f"cand_{i}": SimpleNamespace(score=0.0) for i in range(2)}
        )

    monkeypatch.setattr(recall.store, "list_memories", fake_list)
    monkeypatch.setattr(recall, "jev_ask", fake_ask)

    assert await recall.recall_memories(None, 1, "my BAJA rights issue") == ""


@pytest.mark.asyncio
async def test_scan_falls_back_to_retrieval_when_no_judge(monkeypatch):
    """JEV and the LLM scorer both down → classic pipeline still narrows."""
    mem = _cand("holds 2000 BAJA shares")

    async def fake_list(db, user_id, limit=50, offset=0):
        return [mem]

    async def no_jev(state, questions):
        return None

    async def no_llm(query, candidates):
        return None

    async def fake_gather(*args, **kwargs):
        return [(mem, 0.9)], {mem.id: 0.9}

    monkeypatch.setattr(recall.store, "list_memories", fake_list)
    monkeypatch.setattr(recall, "jev_ask", no_jev)
    monkeypatch.setattr(recall, "_llm_rerank_scores", no_llm)
    monkeypatch.setattr(recall, "_gather_candidates", fake_gather)

    out = await recall.recall_memories(None, 1, "q")
    assert "BAJA" in out


@pytest.mark.asyncio
async def test_scan_unions_retrieval_beyond_cap(monkeypatch):
    """Over the scan cap, retrieval hits stay eligible alongside the newest."""
    monkeypatch.setattr(settings, "MEMORY_SCAN_MAX", 2)
    mems = [_cand("recent a"), _cand("recent b")]
    old = _cand("old but directly relevant")

    async def fake_list(db, user_id, limit=50, offset=0):
        return mems[:limit]

    async def fake_gather(*args, **kwargs):
        return [(old, 0.8)], {old.id: 0.8}

    seen = {}

    async def fake_ask(state, questions):
        seen["n"] = len(questions)
        return SimpleNamespace(
            scores={
                f"cand_{i}": SimpleNamespace(score=3.0)
                for i in range(len(questions))
            }
        )

    monkeypatch.setattr(recall.store, "list_memories", fake_list)
    monkeypatch.setattr(recall, "_gather_candidates", fake_gather)
    monkeypatch.setattr(recall, "jev_ask", fake_ask)

    out = await recall.recall_memories(None, 1, "q")
    assert seen["n"] == 3  # 2 scanned + 1 retrieved beyond the cap
    assert "old but directly relevant" in out
