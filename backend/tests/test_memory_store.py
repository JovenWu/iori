"""Memory store against real Postgres: CRUD, ownership, FTS, vector, cap."""

import pytest
from unittest.mock import AsyncMock

from app.memory import store
from app.models.memory import Memory
from app.models.user import User


def _vec(axis: int) -> list[float]:
    v = [0.0] * 1536
    v[axis] = 1.0
    return v


@pytest.fixture
def fake_embed(monkeypatch):
    """Axis-mapped vectors: 'coffee' → e0, everything else → e1."""

    async def _embed(text: str) -> list[float]:
        return _vec(0) if "coffee" in text.lower() else _vec(1)

    monkeypatch.setattr(store, "embed_text", _embed)


@pytest.mark.asyncio
async def test_add_find_hash_list_count(db, user, fake_embed):
    m = await store.add_memory(db, user.id, "User likes coffee")
    await db.commit()

    assert m.id is not None
    found = await store.find_by_hash(db, user.id, Memory.compute_hash("User likes coffee"))
    assert found is not None and found.id == m.id
    assert await store.count_memories(db, user.id) == 1
    listed = await store.list_memories(db, user.id)
    assert [x.content for x in listed] == ["User likes coffee"]


@pytest.mark.asyncio
async def test_ownership_isolation(db, user, fake_embed):
    other = User(username="other")
    db.add(other)
    await db.commit()
    await db.refresh(other)

    await store.add_memory(db, user.id, "User likes coffee")
    await db.commit()

    assert await store.list_memories(db, other.id) == []
    assert await store.vector_search(db, other.id, "coffee") == []
    assert await store.bm25_search(db, other.id, "coffee") == []


@pytest.mark.asyncio
async def test_update_and_delete(db, user, fake_embed):
    m = await store.add_memory(db, user.id, "User likes coffee")
    await db.commit()

    updated = await store.update_memory(db, m.id, "User likes tea", user.id)
    assert updated is not None
    assert updated.content == "User likes tea"
    assert updated.hash == Memory.compute_hash("User likes tea")

    # Wrong owner cannot update.
    assert await store.update_memory(db, m.id, "x", user.id + 999) is None

    await store.delete_memory(db, m.id, user.id)
    await db.commit()
    assert await store.count_memories(db, user.id) == 0


@pytest.mark.asyncio
async def test_bm25_search_keyword_match(db, user, fake_embed):
    await store.add_memory(db, user.id, "User likes black coffee")
    await store.add_memory(db, user.id, "User holds shares of BBCA")
    await db.commit()

    hits = await store.bm25_search(db, user.id, "coffee")
    assert [m.content for m, _ in hits] == ["User likes black coffee"]

    # Query with no lexical overlap → empty.
    assert await store.bm25_search(db, user.id, "bonds") == []


@pytest.mark.asyncio
async def test_vector_search_orders_by_cosine(db, user, fake_embed):
    near = await store.add_memory(db, user.id, "User likes coffee")
    far = await store.add_memory(db, user.id, "User holds shares of BBCA")
    await db.commit()

    # Query embeds as axis 0 → the "coffee" memory is an exact match.
    hits = await store.vector_search(db, user.id, "which coffee")
    assert hits[0][0].id == near.id
    assert hits[0][1] == pytest.approx(1.0)
    assert hits[1][0].id == far.id
    assert hits[1][1] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_enforce_cap_evicts_oldest(db, user, fake_embed):
    for i in range(5):
        await store.add_memory(db, user.id, f"User fact {i}")
    await db.commit()

    evicted = await store.enforce_cap(db, user.id, 3)
    await db.commit()
    assert evicted == 2
    assert await store.count_memories(db, user.id) == 3

    # Already under the cap → no-op.
    assert await store.enforce_cap(db, user.id, 3) == 0
