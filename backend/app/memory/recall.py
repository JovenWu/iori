"""Memory recall: JEV judges the full memory set first, hybrid retrieval as
the no-judge fallback.

The candidate stage is a full scan, not vector+BM25 — a memory phrased
nothing like the query would never reach the reranker through retrieval,
so JEV scores every stored memory directly (bounded by MEMORY_SCAN_MAX,
unioned with retrieval hits beyond it). Judging stays JEV-first: one
system_one call carries a Score question per candidate, the LLM scorer
takes over when TypeSafe is unavailable, and the classic normalize →
vector + BM25 → RRF → rerank pipeline only runs when no judge answers.
"""

import logging
from typing import Any, NamedTuple

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.jev import Score, jev_ask
from app.core.llm import get_chat_model
from app.memory import store
from app.models.memory import Memory

logger = logging.getLogger(__name__)


class RankedMemory(NamedTuple):
    memory: Memory
    vector_score: float
    rerank_score: float


# ---------------------------------------------------------------------------
# Stage 0 — query normalization (HyDE-style)
# ---------------------------------------------------------------------------

_NORMALIZE_SYSTEM = """You are a query reformulator for long-term memory search.

Your job: rewrite the user's question or statement into ONE short factual sentence in English, using the same shape facts are stored in: "User [predicate] [object]".

Rules:
- Always start with "User" as the subject
- Use a short declarative sentence (not a question)
- Focus on the TOPIC being searched, not the act of searching
- Return ONLY the one fact sentence — no explanation, no quotes

Examples:
- "what is my name?" → "User is named [name]"
- "siapa nama saya?" → "User is named [name]"
- "saham apa yang saya pegang?" → "User holds shares of [ticker]"
- "do I like spicy food?" → "User likes or dislikes spicy food"
- "saya investor konservatif" → "User is a conservative investor"
"""

_normalizer = get_chat_model(
    settings.CLASSIFIER_MODEL,
    temperature=0,
    timeout=30,
    max_retries=2,
)


async def _normalize_query(query: str) -> str:
    """Rewrite the raw query into the stored-fact shape so cosine distance and
    BM25 overlap shrink. Falls back to the raw query on any error."""
    try:
        result = await _normalizer.ainvoke(
            [SystemMessage(content=_NORMALIZE_SYSTEM), HumanMessage(content=query)]
        )
        normalized = result.content.strip()
        return normalized or query
    except Exception:
        logger.warning("_normalize_query: failed, using raw query")
        return query


# ---------------------------------------------------------------------------
# Stage 1c — reciprocal rank fusion
# ---------------------------------------------------------------------------


def rrf_merge(
    semantic: list[tuple[Any, float]],
    bm25: list[tuple[Any, float]],
    k: int = 60,
) -> list[tuple[Any, float]]:
    """Fuse two ranked lists by item id: score += 1/(k+rank) per list."""
    scores: dict = {}
    items: dict = {}
    for rank, (item, _) in enumerate(semantic, start=1):
        scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (k + rank)
        items[item.id] = item
    for rank, (item, _) in enumerate(bm25, start=1):
        scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (k + rank)
        items[item.id] = item
    ordered = sorted(scores, key=lambda i: scores[i], reverse=True)
    return [(items[i], scores[i]) for i in ordered]


# ---------------------------------------------------------------------------
# Stage 2 — rerank (JEV Score fan-out, LLM fallback, vector order last)
# ---------------------------------------------------------------------------

_RERANK_LEVELS = ["unrelated", "tangential", "on-topic", "directly relevant"]


class _ScoredCandidate(BaseModel):
    index: int = Field(description="0-based index into the candidate list")
    relevance: float = Field(ge=0.0, le=1.0)


class _RerankResult(BaseModel):
    scores: list[_ScoredCandidate]


_RERANK_SYSTEM = """You are a memory relevance ranker for an AI assistant.

Given a user query and a numbered list of remembered facts about that user, score EACH fact 0.0–1.0:
- 1.0 = the fact directly answers or meaningfully contextualises the query
- 0.5 = tangentially related, may add useful background
- 0.0 = unrelated

Return a score for EVERY fact using its index."""

_RERANK_TEMPLATE = "Query: {query}\n\nCandidate memories (index | content):\n{candidates}"

_llm_reranker = get_chat_model(
    settings.CLASSIFIER_MODEL,
    temperature=0,
    timeout=30,
    max_retries=2,
).with_structured_output(_RerankResult)


async def _jev_rerank_scores(
    query: str, candidates: list[tuple[Memory, float]]
) -> dict[int, float] | None:
    """One JEV call with a Score question per candidate → index → 0..1 score.
    Returns None when JEV is unavailable so the caller falls back."""
    questions = {
        f"cand_{i}": Score(
            instructions=(
                "How relevant is this candidate memory to the user's query?"
            ),
            criteria=list(_RERANK_LEVELS),
        )
        for i in range(len(candidates))
    }
    state = {
        "query": query,
        "candidates": [
            {"index": i, "memory": memory.content}
            for i, (memory, _) in enumerate(candidates)
        ],
    }
    result = await jev_ask(state, questions)
    if result is None:
        return None

    top_level = len(_RERANK_LEVELS) - 1
    scores: dict[int, float] = {}
    for i in range(len(candidates)):
        answer = result.scores.get(f"cand_{i}")
        if answer is not None:
            scores[i] = max(0.0, min(1.0, answer.score / top_level))
    return scores


async def _llm_rerank_scores(
    query: str, candidates: list[tuple[Memory, float]]
) -> dict[int, float] | None:
    listing = "\n".join(
        f"{i} | {m.content}" for i, (m, _) in enumerate(candidates)
    )
    try:
        result: _RerankResult = await _llm_reranker.ainvoke(
            [
                SystemMessage(content=_RERANK_SYSTEM),
                HumanMessage(
                    content=_RERANK_TEMPLATE.format(
                        query=query, candidates=listing
                    )
                ),
            ]
        )
        return {s.index: s.relevance for s in result.scores}
    except Exception:
        logger.exception("_llm_rerank_scores: LLM call failed")
        return None


def _apply_rerank_filter(
    candidates: list[tuple[Memory, float]],
    score_map: dict[int, float],
    cosine_scores: dict,
    threshold: float,
    vector_floor: float,
) -> list[RankedMemory]:
    """Keep candidates ≥ threshold; if none survive, rescue the strongest
    cosine hit at/above vector_floor."""
    ranked = [
        RankedMemory(m, cosine_scores.get(m.id, 0.0), score_map.get(i, 0.0))
        for i, (m, _) in enumerate(candidates)
        if score_map.get(i, 0.0) >= threshold
    ]
    if not ranked:
        best: RankedMemory | None = None
        for i, (m, _) in enumerate(candidates):
            cosine = cosine_scores.get(m.id, 0.0)
            if cosine >= vector_floor and (best is None or cosine > best.vector_score):
                best = RankedMemory(m, cosine, score_map.get(i, 0.0))
        if best is not None:
            ranked = [best]
    ranked.sort(key=lambda r: (r.rerank_score, r.vector_score), reverse=True)
    return ranked


async def rerank_candidates(
    query: str,
    candidates: list[tuple[Memory, float]],
    cosine_scores: dict | None = None,
) -> list[RankedMemory]:
    """Score each candidate for relevance; threshold + floor-rescue applied."""
    if not candidates:
        return []

    score_map = await _jev_rerank_scores(query, candidates)
    if score_map is None:
        score_map = await _llm_rerank_scores(query, candidates)
    if score_map is None:
        # Last resort: vector/RRF order as the relevance proxy.
        return sorted(
            [RankedMemory(m, vs, vs) for m, vs in candidates],
            key=lambda r: r.rerank_score,
            reverse=True,
        )

    return _apply_rerank_filter(
        candidates,
        score_map,
        cosine_scores or {},
        settings.MEMORY_RERANK_THRESHOLD,
        settings.MEMORY_VECTOR_FLOOR,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def _gather_candidates(
    db: AsyncSession, user_id: int, query: str
) -> tuple[list[tuple[Memory, float]], dict]:
    """Shared retrieval core: normalized query → both arms → RRF merge.

    Returns (merged_candidates, cosine_score_by_id). Empty list when neither
    arm produced anything.
    """
    normalized = await _normalize_query(query)

    semantic_raw = await store.vector_search(
        db, user_id, normalized, top_k=settings.MEMORY_RETRIEVAL_CANDIDATES
    )
    cosine_scores = {m.id: s for m, s in semantic_raw}
    semantic = [
        (m, s)
        for m, s in semantic_raw
        if s >= settings.MEMORY_RETRIEVAL_THRESHOLD
    ]

    bm25 = await store.bm25_search(
        db, user_id, normalized, top_k=settings.MEMORY_BM25_CANDIDATES
    )

    if not semantic and not bm25:
        return [], cosine_scores

    return rrf_merge(semantic, bm25, k=settings.MEMORY_RRF_K), cosine_scores


async def _recall_ranked(
    db: AsyncSession, user_id: int, query: str
) -> list[RankedMemory]:
    """JEV judges the whole memory set, not just what retrieval surfaces.

    A memory can be relevant yet phrased nothing like the query — semantic
    distance and BM25 would both drop it before the reranker ever saw it.
    Scoring every stored memory (bounded by MEMORY_SCAN_MAX; above that, the
    newest N plus hybrid-retrieval hits) lets the judge decide on content.
    When no judge is reachable at all, the classic retrieval pipeline
    remains as the narrowing fallback.
    """
    memories = await store.list_memories(
        db, user_id, limit=settings.MEMORY_SCAN_MAX
    )
    merged: list[tuple[Memory, float]] = []
    cosine_scores: dict = {}
    if len(memories) >= settings.MEMORY_SCAN_MAX:
        # The scan window is full — older memories may exist beyond it, so
        # union in whatever retrieval surfaces to keep them eligible.
        merged, cosine_scores = await _gather_candidates(db, user_id, query)
    seen = {m.id for m in memories}
    candidates = [(m, 0.0) for m in memories] + [
        x for x in merged if x[0].id not in seen
    ]

    if candidates:
        score_map = await _jev_rerank_scores(query, candidates)
        if score_map is None:
            score_map = await _llm_rerank_scores(query, candidates)
        if score_map is not None:
            # No cosine scores on the scan path — the judge is the arbiter,
            # so "nothing relevant" honestly yields nothing.
            return _apply_rerank_filter(
                candidates,
                score_map,
                cosine_scores,
                settings.MEMORY_RERANK_THRESHOLD,
                settings.MEMORY_VECTOR_FLOOR,
            )

    if not merged:
        merged, cosine_scores = await _gather_candidates(db, user_id, query)
    return await rerank_candidates(query, merged, cosine_scores)


async def recall_memories(
    db: AsyncSession,
    user_id: int,
    query: str,
    top_k: int = settings.MEMORY_TOP_K,
) -> str:
    """Return the fenced memory block for prompt injection, or "" if none."""
    if not query.strip():
        return ""

    ranked = (await _recall_ranked(db, user_id, query))[:top_k]
    if not ranked:
        return ""

    lines = "\n".join(f"- {r.memory.content}" for r in ranked)
    return f"[LONG-TERM MEMORIES]\n{lines}\n[/LONG-TERM MEMORIES]"


async def recall_scored(
    db: AsyncSession,
    user_id: int,
    query: str,
    top_k: int = settings.MEMORY_TOP_K,
) -> list[dict]:
    """Same pipeline as recall_memories but structured — for the search API."""
    if not query.strip():
        return []

    ranked = await _recall_ranked(db, user_id, query)
    return [
        {
            "memory": r.memory,
            "vector_score": r.vector_score,
            "rerank_score": r.rerank_score,
        }
        for r in ranked[:top_k]
    ]
