"""Memory CRUD + pgvector cosine search + Postgres ts_rank keyword search.

Callers own the transaction (commit/rollback); every function only flushes.
"""

import logging
import re
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.embeddings import embed_text
from app.models.memory import Memory

logger = logging.getLogger(__name__)


async def add_memory(
    db: AsyncSession,
    user_id: int,
    content: str,
    source_thread_id: UUID | str | None = None,
) -> Memory:
    embedding = await embed_text(content)
    memory = Memory(
        user_id=user_id,
        content=content,
        embedding=embedding,
        hash=Memory.compute_hash(content),
        source_thread_id=source_thread_id,
    )
    db.add(memory)
    await db.flush()
    await db.refresh(memory)
    return memory


async def vector_search(
    db: AsyncSession,
    user_id: int,
    query: str,
    top_k: int = 10,
) -> list[tuple[Memory, float]]:
    """(Memory, cosine_similarity) pairs ordered most-similar first."""
    query_embedding = await embed_text(query)
    distance = Memory.embedding.cosine_distance(query_embedding)
    result = await db.execute(
        select(Memory, distance.label("distance"))
        .where(Memory.user_id == user_id)
        .order_by(distance)
        .limit(top_k)
    )
    return [
        (row.Memory, round(max(0.0, 1.0 - float(row.distance)), 4))
        for row in result.all()
    ]


def _build_tsquery(query: str) -> str:
    """OR-joined tsquery — partial matches work for mixed id/en queries."""
    tokens = re.findall(r"\w+", query.lower())
    return " | ".join(f"'{t}'" for t in tokens)


async def bm25_search(
    db: AsyncSession,
    user_id: int,
    query: str,
    top_k: int = 20,
) -> list[tuple[Memory, float]]:
    """Keyword arm via Postgres ts_rank on the GIN-indexed content column."""
    tsquery = _build_tsquery(query)
    if not tsquery:
        return []

    sql = text(
        """
        SELECT id,
               ts_rank(to_tsvector('simple', content), to_tsquery('simple', :tsquery)) AS rank
        FROM memories
        WHERE user_id = :user_id
          AND to_tsvector('simple', content) @@ to_tsquery('simple', :tsquery)
        ORDER BY rank DESC
        LIMIT :top_k
        """
    )
    try:
        rows = (
            await db.execute(
                sql, {"tsquery": tsquery, "user_id": user_id, "top_k": top_k}
            )
        ).all()
    except Exception:
        logger.exception("bm25_search: FTS failed for user %d", user_id)
        return []

    rank_map = {row.id: float(row.rank) for row in rows}
    if not rank_map:
        return []

    # Two-query pattern: scores by id first, then ORM objects by id.
    result = await db.execute(select(Memory).where(Memory.id.in_(rank_map)))
    by_id = {m.id: m for m in result.scalars().all()}
    return [(by_id[mid], rank_map[mid]) for mid in rank_map if mid in by_id]


async def update_memory(
    db: AsyncSession,
    memory_id: str | UUID,
    new_content: str,
    user_id: int,
) -> Memory | None:
    result = await db.execute(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    memory = result.scalars().first()
    if memory is None:
        return None
    memory.content = new_content
    memory.embedding = await embed_text(new_content)
    memory.hash = Memory.compute_hash(new_content)
    await db.flush()
    await db.refresh(memory)
    return memory


async def delete_memory(db: AsyncSession, memory_id: str | UUID, user_id: int) -> None:
    await db.execute(
        delete(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    await db.flush()


async def list_memories(
    db: AsyncSession, user_id: int, limit: int = 50, offset: int = 0
) -> list[Memory]:
    result = await db.execute(
        select(Memory)
        .where(Memory.user_id == user_id)
        .order_by(Memory.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def count_memories(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(func.count()).select_from(Memory).where(Memory.user_id == user_id)
    )
    return int(result.scalar_one())


async def find_by_hash(
    db: AsyncSession, user_id: int, content_hash: str
) -> Memory | None:
    result = await db.execute(
        select(Memory)
        .where(Memory.user_id == user_id, Memory.hash == content_hash)
        .limit(1)
    )
    return result.scalars().first()


async def enforce_cap(db: AsyncSession, user_id: int, max_per_user: int) -> int:
    """Evict oldest-by-updated_at memories above the cap. Returns count removed."""
    if max_per_user <= 0:
        return 0
    total = await count_memories(db, user_id)
    if total <= max_per_user:
        return 0
    n_evict = total - max_per_user
    victims = (
        select(Memory.id)
        .where(Memory.user_id == user_id)
        .order_by(Memory.updated_at.asc(), Memory.id.asc())
        .limit(n_evict)
        .scalar_subquery()
    )
    await db.execute(
        delete(Memory).where(Memory.user_id == user_id, Memory.id.in_(victims))
    )
    await db.flush()
    return n_evict
