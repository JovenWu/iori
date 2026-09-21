"""Thread digests: per-thread searchable gists for cross-thread recall.

A digest is a 2–4 sentence third-person summary of a whole conversation,
embedded so other turns can surface "related past chats". Regeneration is
debounced — at most once per THREAD_DIGEST_STALE_TURNS new turns.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm import get_chat_model
from app.memory.embeddings import embed_text
from app.memory.recall import rrf_merge
from app.models.thread_digest import ThreadDigest

logger = logging.getLogger(__name__)

_DIGEST_SYSTEM = """You write a short, searchable digest of a conversation between a user and an AI assistant.

Rules:
- 2 to 4 sentences, third person, describing what the user asked about and the key topics, decisions, or conclusions.
- Focus on durable content worth recalling in a future session (stocks analyzed, comparisons made, decisions reached), not pleasantries.
- Do not invent facts. If the conversation is trivial, return a single short sentence.
- Output only the digest text, no preamble."""

_digest_llm = get_chat_model(
    settings.CLASSIFIER_MODEL,
    temperature=0,
    timeout=30,
    max_retries=2,
)


def _uuid_or_none(value) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


async def get_digest(db: AsyncSession, thread_id: str | UUID) -> ThreadDigest | None:
    result = await db.execute(
        select(ThreadDigest).where(ThreadDigest.thread_id == thread_id)
    )
    return result.scalars().first()


async def upsert_digest(
    db: AsyncSession,
    user_id: int,
    thread_id: str | UUID,
    title: str | None,
    digest: str,
    message_count: int,
) -> ThreadDigest:
    embedding = await embed_text(digest)
    existing = await get_digest(db, thread_id)
    if existing is None:
        existing = ThreadDigest(
            thread_id=_uuid_or_none(thread_id),
            user_id=user_id,
            title=title,
            digest=digest,
            embedding=embedding,
            message_count=message_count,
            stale_turns=0,
            last_turn_at=datetime.now(timezone.utc),
        )
        db.add(existing)
    else:
        existing.title = title or existing.title
        existing.digest = digest
        existing.embedding = embedding
        existing.message_count = message_count
        existing.stale_turns = 0
        existing.last_turn_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(existing)
    return existing


async def bump_stale_turns(db: AsyncSession, thread_id: str | UUID) -> None:
    digest = await get_digest(db, thread_id)
    if digest is not None:
        digest.stale_turns = (digest.stale_turns or 0) + 1
        digest.last_turn_at = datetime.now(timezone.utc)
        await db.flush()


async def mark_stale(db: AsyncSession, thread_id: str | UUID) -> None:
    """Force regeneration on the next turn (e.g. after a turn was deleted)."""
    digest = await get_digest(db, thread_id)
    if digest is not None:
        digest.stale_turns = settings.THREAD_DIGEST_STALE_TURNS
        await db.flush()


async def delete_digest(db: AsyncSession, thread_id: str | UUID) -> None:
    await db.execute(
        delete(ThreadDigest).where(ThreadDigest.thread_id == thread_id)
    )
    await db.flush()


# ---------------------------------------------------------------------------
# Search (same hybrid shape as memory recall — vector + BM25 + RRF)
# ---------------------------------------------------------------------------


async def vector_search_digests(
    db: AsyncSession,
    user_id: int,
    query: str,
    exclude_thread_id: str | UUID | None,
    top_k: int,
) -> list[tuple[ThreadDigest, float]]:
    query_embedding = await embed_text(query)
    distance = ThreadDigest.embedding.cosine_distance(query_embedding)
    stmt = (
        select(ThreadDigest, distance.label("distance"))
        .where(ThreadDigest.user_id == user_id)
        .order_by(distance)
        .limit(top_k)
    )
    excluded = _uuid_or_none(exclude_thread_id)
    if excluded is not None:
        stmt = stmt.where(ThreadDigest.thread_id != excluded)
    result = await db.execute(stmt)
    return [
        (row.ThreadDigest, round(max(0.0, 1.0 - float(row.distance)), 4))
        for row in result.all()
    ]


def _build_tsquery(query: str) -> str:
    tokens = re.findall(r"\w+", query.lower())
    return " | ".join(f"'{t}'" for t in tokens)


async def bm25_search_digests(
    db: AsyncSession,
    user_id: int,
    query: str,
    exclude_thread_id: str | UUID | None,
    top_k: int,
) -> list[tuple[ThreadDigest, float]]:
    tsquery = _build_tsquery(query)
    if not tsquery:
        return []

    sql = text(
        """
        SELECT id,
               ts_rank(
                   to_tsvector('simple', coalesce(title, '') || ' ' || digest),
                   to_tsquery('simple', :tsquery)
               ) AS rank
        FROM thread_digests
        WHERE user_id = :user_id
          AND (:excluded IS NULL OR thread_id != CAST(:excluded AS uuid))
          AND to_tsvector('simple', coalesce(title, '') || ' ' || digest)
              @@ to_tsquery('simple', :tsquery)
        ORDER BY rank DESC
        LIMIT :top_k
        """
    )
    excluded = str(_uuid_or_none(exclude_thread_id) or "") or None
    try:
        rows = (
            await db.execute(
                sql,
                {
                    "tsquery": tsquery,
                    "user_id": user_id,
                    "excluded": excluded,
                    "top_k": top_k,
                },
            )
        ).all()
    except Exception:
        logger.exception("bm25_search_digests: FTS failed for user %d", user_id)
        return []

    rank_map = {row.id: float(row.rank) for row in rows}
    if not rank_map:
        return []

    result = await db.execute(
        select(ThreadDigest).where(ThreadDigest.id.in_(rank_map))
    )
    by_id = {d.id: d for d in result.scalars().all()}
    return [(by_id[i], rank_map[i]) for i in rank_map if i in by_id]


async def get_related_threads(
    db: AsyncSession,
    user_id: int,
    query: str,
    exclude_thread_id: str | UUID | None = None,
    top_k: int = settings.THREAD_SIGNAL_TOP_K,
) -> list[ThreadDigest]:
    """Hybrid digest search — no rerank on the signal path."""
    if not query.strip():
        return []

    semantic_raw = await vector_search_digests(
        db, user_id, query, exclude_thread_id, settings.THREAD_RECALL_CANDIDATES
    )
    semantic = [
        (d, s) for d, s in semantic_raw if s >= settings.THREAD_RECALL_THRESHOLD
    ]
    bm25 = await bm25_search_digests(
        db, user_id, query, exclude_thread_id, settings.THREAD_RECALL_BM25_CANDIDATES
    )
    if not semantic and not bm25:
        return []

    merged = rrf_merge(semantic, bm25, k=settings.THREAD_RECALL_RRF_K)
    return [d for d, _ in merged[:top_k]]


def format_thread_signal(digests: list[ThreadDigest]) -> str:
    """Render the compact read-only "related past chats" block."""
    if not digests:
        return ""
    lines = []
    for d in digests:
        title = d.title or "Untitled chat"
        gist = (d.digest or "").strip().splitlines()[0][:120].rstrip() if d.digest else ""
        lines.append(f"- {title} — {gist}")
    return "Related past chats:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Debounced maintenance
# ---------------------------------------------------------------------------


def _messages_to_text(messages: Sequence[BaseMessage]) -> str:
    lines = []
    for m in messages:
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            lines.append(f"User: {m.content}")
        elif isinstance(m, AIMessage) and isinstance(m.content, str):
            lines.append(f"Assistant: {m.content}")
    return "\n".join(lines)


async def _generate_digest(summary: str, messages: Sequence[BaseMessage]) -> str:
    body = summary.strip() if summary and summary.strip() else _messages_to_text(messages)
    if not body.strip():
        return ""
    try:
        resp = await _digest_llm.ainvoke(
            [
                SystemMessage(content=_DIGEST_SYSTEM),
                HumanMessage(content=f"Conversation material to digest:\n{body}"),
            ]
        )
        digest = (resp.content or "").strip()
    except Exception:
        logger.exception("_generate_digest: LLM call failed")
        return ""
    return digest[: settings.THREAD_DIGEST_MAX_CHARS].rstrip()


async def maintain_digest(
    db: AsyncSession,
    user_id: int,
    thread_id: str,
    title: str | None,
    summary: str,
    messages: Sequence[BaseMessage],
) -> None:
    """Post-turn upkeep. Best-effort — never raises."""
    try:
        existing = await get_digest(db, thread_id)
        threshold = settings.THREAD_DIGEST_STALE_TURNS

        should_regenerate = existing is None or (
            existing.stale_turns + 1 >= threshold
        )
        if should_regenerate:
            digest = await _generate_digest(summary, messages)
            if not digest:
                if existing is not None:
                    await bump_stale_turns(db, thread_id)
                    await db.commit()
                return
            await upsert_digest(
                db,
                user_id=user_id,
                thread_id=thread_id,
                title=title,
                digest=digest,
                message_count=len(messages),
            )
        else:
            await bump_stale_turns(db, thread_id)

        await db.commit()
    except Exception:
        logger.exception("maintain_digest: failed for thread %s", thread_id)
        await db.rollback()
