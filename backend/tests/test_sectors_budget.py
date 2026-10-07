"""Global Sectors credit budget — atomic reservations, refunds, the cap.

`try_spend`/`refund`/`snapshot` open their own sessions, so every test needs
`bound_session_maker` to rebind them to the per-test engine.
"""

import pytest

from app.core.config import settings
from app.sectors import budget, cache
from app.sectors.freshness import Freshness

# db wipes all tables between tests; bound_session_maker rebinds the module's
# own sessions to the per-test engine.
pytestmark = pytest.mark.usefixtures("db", "bound_session_maker")


@pytest.mark.asyncio
async def test_spend_reserves_and_snapshot_reports():
    assert await budget.try_spend(10) is True
    snap = await budget.snapshot()
    assert snap["spent"] == 10
    assert snap["budget"] == settings.SECTORS_CREDIT_BUDGET
    assert snap["remaining"] == settings.SECTORS_CREDIT_BUDGET - 10


@pytest.mark.asyncio
async def test_spend_never_exceeds_cap(monkeypatch):
    monkeypatch.setattr(settings, "SECTORS_CREDIT_BUDGET", 5)
    assert await budget.try_spend(4) is True
    assert await budget.try_spend(2) is False  # 4+2 > 5 — refused, unchanged
    assert await budget.try_spend(1) is True
    assert (await budget.snapshot())["spent"] == 5
    assert await budget.try_spend(1) is False


@pytest.mark.asyncio
async def test_refund_releases_and_floors_at_zero():
    await budget.try_spend(3)
    await budget.refund(3)
    await budget.refund(10)  # over-refund must not push spent negative
    assert (await budget.snapshot())["spent"] == 0


async def _spy_client(monkeypatch, status=200, data=None):
    calls = []

    async def fake_get(path, params=None):
        calls.append((path, params))
        return status, data or {"ok": True}

    monkeypatch.setattr(cache.client, "get", fake_get)
    return calls


@pytest.mark.asyncio
async def test_miss_reserves_and_hit_stays_free(monkeypatch):
    calls = await _spy_client(monkeypatch)
    res = await cache.cached_get(
        "ep", "/v1/a", {"x": 1}, Freshness.STATIC, credits=3
    )
    assert res.status == 200 and res.source == "upstream"
    assert (await budget.snapshot())["spent"] == 3

    res = await cache.cached_get(
        "ep", "/v1/a", {"x": 1}, Freshness.STATIC, credits=3
    )
    assert res.source == "hit"
    assert len(calls) == 1 and (await budget.snapshot())["spent"] == 3


@pytest.mark.asyncio
async def test_free_status_refunds_the_reservation(monkeypatch):
    await _spy_client(monkeypatch, status=500, data={"err": "x"})
    res = await cache.cached_get("ep", "/v1/b", {}, Freshness.STATIC)
    assert res.status == 500
    assert (await budget.snapshot())["spent"] == 0


@pytest.mark.asyncio
async def test_exhausted_budget_blocks_upstream(monkeypatch):
    monkeypatch.setattr(settings, "SECTORS_CREDIT_BUDGET", 1)
    calls = await _spy_client(monkeypatch)
    await cache.cached_get("ep", "/v1/c", {}, Freshness.STATIC)  # spends 1
    res = await cache.cached_get("ep", "/v1/d", {}, Freshness.STATIC)
    assert res.status == 429
    assert res.data["error"] == "sectors credit budget exhausted"
    assert len(calls) == 1  # the second fetch never reached upstream


@pytest.mark.asyncio
async def test_exhausted_budget_serves_stored_entry(monkeypatch):
    monkeypatch.setattr(settings, "SECTORS_CREDIT_BUDGET", 1)
    await _spy_client(monkeypatch)
    await cache.cached_get("ep", "/v1/e", {}, Freshness.STATIC)
    # Budget now spent; a refresh still can't pay, but the stored entry
    # answers instead of failing — same rule as an upstream outage.
    res = await cache.cached_get(
        "ep", "/v1/e", {}, Freshness.STATIC, refresh=True
    )
    assert res.status == 200 and res.source == "stale_fallback"
