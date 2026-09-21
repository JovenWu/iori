"""Sectors response cache: permanent store, stale hints, refresh override,
single-flight, billable-status filtering, stale-on-error fallback."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.sectors_cache import SectorsCache
from app.sectors import cache, client
from app.sectors.freshness import Freshness

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _bind_cache_db(bound_session_maker):
    yield


def _fake_get(status=200, data=None, calls=None):
    async def fake(path, params=None):
        if calls is not None:
            calls.append((path, params))
        return status, data if data is not None else {"ok": True}

    return fake


async def test_miss_fetches_and_stores(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))

    result = await cache.cached_get(
        "daily", "/v2/daily/BBCA/", {"end": "2026-07-08"}, Freshness.EOD
    )
    assert result.status == 200 and result.source == "upstream" and not result.stale
    assert len(calls) == 1

    row = (await db.execute(select(SectorsCache))).scalar_one()
    assert row.endpoint == "daily"
    assert row.freshness == Freshness.HISTORICAL.value  # end in the past
    assert row.credits == 1 and row.hits == 0


async def test_hit_skips_upstream(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    params = {"end": "2026-07-08"}

    await cache.cached_get("daily", "/v2/daily/BBCA/", params, Freshness.EOD)
    result = await cache.cached_get("daily", "/v2/daily/BBCA/", params, Freshness.EOD)

    assert len(calls) == 1
    assert result.source == "hit"
    row = (await db.execute(select(SectorsCache))).scalar_one()
    assert row.hits == 1


async def test_hit_reports_stale_hint(db, monkeypatch):
    monkeypatch.setattr(client, "get", _fake_get())
    await cache.cached_get("daily", "/v2/daily/BBCA/", {}, Freshness.EOD)

    # Age the entry past the last refresh boundary.
    old = datetime.now(timezone.utc) - timedelta(days=3)
    row = (await db.execute(select(SectorsCache))).scalar_one()
    row.fetched_at = old
    await db.commit()

    result = await cache.cached_get("daily", "/v2/daily/BBCA/", {}, Freshness.EOD)
    assert result.source == "hit" and result.stale and result.fetched_at == old.isoformat()


async def test_refresh_overwrites_entry(db, monkeypatch):
    calls = []
    monkeypatch.setattr(
        client, "get", _fake_get(data={"v": 1}, calls=calls)
    )
    params = {"end": "2026-07-08"}
    await cache.cached_get("daily", "/v2/daily/BBCA/", params, Freshness.EOD)

    monkeypatch.setattr(client, "get", _fake_get(data={"v": 2}, calls=calls))
    result = await cache.cached_get(
        "daily", "/v2/daily/BBCA/", params, Freshness.EOD, refresh=True
    )
    assert result.source == "upstream" and result.data == {"v": 2}
    assert len(calls) == 2
    row = (await db.execute(select(SectorsCache))).scalar_one()
    assert row.payload == {"v": 2} and row.hits == 0  # hits survive semantics: not reset


async def test_404_cached_but_400_not(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(status=404, calls=calls))
    p = {"end": "2026-07-08"}
    await cache.cached_get("daily", "/v2/daily/XXXX/", p, Freshness.EOD)
    r = await cache.cached_get("daily", "/v2/daily/XXXX/", p, Freshness.EOD)
    assert r.status == 404 and r.source == "hit" and len(calls) == 1

    calls.clear()
    monkeypatch.setattr(client, "get", _fake_get(status=400, calls=calls))
    await cache.cached_get("daily", "/v2/daily/BAD/", {"end": "bad"}, Freshness.EOD)
    await cache.cached_get("daily", "/v2/daily/BAD/", {"end": "bad"}, Freshness.EOD)
    assert len(calls) == 2  # free responses are never stored


async def test_single_flight(db, monkeypatch):
    calls = []

    async def slow_get(path, params=None):
        calls.append(path)
        await asyncio.sleep(0.05)
        return 200, {"ok": True}

    monkeypatch.setattr(client, "get", slow_get)
    r1, r2 = await asyncio.gather(
        cache.cached_get("daily", "/v2/daily/BBCA/", {}, Freshness.EOD),
        cache.cached_get("daily", "/v2/daily/BBCA/", {}, Freshness.EOD),
    )
    assert len(calls) == 1
    assert r1.data == r2.data == {"ok": True}


async def test_upstream_failure_falls_back_to_stored(db, monkeypatch):
    monkeypatch.setattr(client, "get", _fake_get(data={"v": 1}))
    params = {"end": "2026-07-08"}
    await cache.cached_get("daily", "/v2/daily/BBCA/", params, Freshness.EOD)

    async def down(path, params=None):
        raise client.SectorsUnavailable("boom")

    monkeypatch.setattr(client, "get", down)
    result = await cache.cached_get(
        "daily", "/v2/daily/BBCA/", params, Freshness.EOD, refresh=True
    )
    assert result.source == "stale_fallback" and result.data == {"v": 1} and result.stale

    with pytest.raises(client.SectorsUnavailable):
        await cache.cached_get("daily", "/v2/daily/GOTO/", params, Freshness.EOD)


async def test_failed_refresh_status_falls_back_to_stored(db, monkeypatch):
    """A 429/5xx on refresh shouldn't surface as an error when a stored
    entry can answer."""
    monkeypatch.setattr(client, "get", _fake_get(data={"v": 1}))
    params = {"end": "2026-07-08"}
    await cache.cached_get("daily", "/v2/daily/BBCA/", params, Freshness.EOD)

    monkeypatch.setattr(client, "get", _fake_get(status=429, data={"error": "limited"}))
    result = await cache.cached_get(
        "daily", "/v2/daily/BBCA/", params, Freshness.EOD, refresh=True
    )
    assert result.source == "stale_fallback" and result.data == {"v": 1} and result.stale


async def test_cache_key_canonicalization():
    a = cache.cache_key("/v2/daily/BBCA/", {"end": "2026-07-08", "start": "2026-06-01"})
    b = cache.cache_key("/v2/daily/BBCA/", {"start": "2026-06-01", "end": "2026-07-08"})
    assert a == b
    c = cache.cache_key("/v2/company/report/BBCA/", {"sections": ["overview", "valuation"]})
    d = cache.cache_key("/v2/company/report/BBCA/", {"sections": ["valuation", "overview"]})
    assert c == d
    # Path params (the symbol) are part of the key — different tickers differ.
    assert a != cache.cache_key(
        "/v2/daily/GOTO/", {"end": "2026-07-08", "start": "2026-06-01"}
    )


async def test_stats_counts_credits(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await cache.cached_get("daily", "/v2/daily/BBCA/", {}, Freshness.EOD)
    await cache.cached_get("daily", "/v2/daily/BBCA/", {}, Freshness.EOD)
    await cache.cached_get(
        "report", "/v2/company/report/BBCA/", {"sections": "a,b"},
        Freshness.EOD, credits=2,
    )
    await cache.cached_get(
        "report", "/v2/company/report/BBCA/", {"sections": "a,b"},
        Freshness.EOD, credits=2,
    )

    stats = await cache.cache_stats()
    assert stats["entries"] == 2
    assert stats["total_hits"] == 2
    assert stats["credits_saved"] == 1 * 1 + 1 * 2  # hit on 1-credit + hit on 2-credit
    assert stats["by_endpoint"]["report"]["credits_saved"] == 2
