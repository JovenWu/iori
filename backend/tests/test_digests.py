"""Thread digest lifecycle and related-thread retrieval."""

import pytest
from unittest.mock import AsyncMock

from app.memory import digests
from app.models.thread import Thread


@pytest.fixture
def fake_embed(monkeypatch):
    monkeypatch.setattr(digests, "embed_text", AsyncMock(return_value=[0.1] * 1536))


async def _thread(db, user, title=None) -> Thread:
    t = Thread(user_id=user.id, title=title)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


@pytest.mark.asyncio
async def test_digest_lifecycle(db, user, fake_embed):
    t = await _thread(db, user, "chat a")

    d = await digests.upsert_digest(db, user.id, t.id, "chat a", "User analyzed banks.", 4)
    assert d.stale_turns == 0
    assert d.message_count == 4

    # Second upsert refreshes digest text and resets staleness.
    await digests.bump_stale_turns(db, t.id)
    assert (await digests.get_digest(db, t.id)).stale_turns == 1
    d = await digests.upsert_digest(db, user.id, t.id, "chat a", "User analyzed banks and telcos.", 8)
    assert d.digest == "User analyzed banks and telcos."
    assert d.stale_turns == 0
    assert d.message_count == 8


@pytest.mark.asyncio
async def test_related_threads_excludes_current(db, user, fake_embed):
    t1 = await _thread(db, user, "banks")
    t2 = await _thread(db, user, "telcos")
    await digests.upsert_digest(db, user.id, t1.id, "banks", "User analyzed bank sector.", 4)
    await digests.upsert_digest(db, user.id, t2.id, "telcos", "User compared telco stocks.", 4)
    await db.commit()

    related = await digests.get_related_threads(
        db, user.id, "bank sector", exclude_thread_id=t2.id
    )
    assert related
    assert all(d.thread_id == t1.id for d in related)

    # Empty query → no signal.
    assert await digests.get_related_threads(db, user.id, "  ") == []


def test_format_thread_signal():
    d = type("D", (), {})()
    d.title = "banks"
    d.digest = "User analyzed bank sector.\nSecond line."
    block = digests.format_thread_signal([d])
    assert "Related past chats:" in block
    assert "- banks — User analyzed bank sector." in block
    assert digests.format_thread_signal([]) == ""
