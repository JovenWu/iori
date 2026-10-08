"""Sectors cache admin endpoints: stats + flush (auth required)."""

import pytest

from app.core.config import settings
from app.sectors import cache
from app.sectors import client as sectors_client
from app.sectors.freshness import Freshness

pytestmark = pytest.mark.asyncio


async def _login(client) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "username": settings.APP_USERNAME,
            "password": settings.APP_PASSWORD,
        },
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_cache_stats_and_flush(client, monkeypatch):
    async def fake_get(path, params=None):
        return 200, {"ok": True}

    monkeypatch.setattr(sectors_client, "get", fake_get)

    # Unauthenticated requests are rejected.
    assert (await client.get("/api/v1/sectors/cache/stats")).status_code == 401
    assert (await client.delete("/api/v1/sectors/cache")).status_code == 401

    headers = await _login(client)

    # One stored entry + one hit → 1 credit saved.
    await cache.cached_get("daily", "/v2/daily/BBCA/", {}, Freshness.EOD)
    await cache.cached_get("daily", "/v2/daily/BBCA/", {}, Freshness.EOD)

    resp = await client.get("/api/v1/sectors/cache/stats", headers=headers)
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["entries"] == 1
    assert stats["total_hits"] == 1
    assert stats["credits_saved"] == 1
    assert stats["by_endpoint"]["daily"]["entries"] == 1

    monkeypatch.setattr(settings, "ADMIN_USERNAME", settings.APP_USERNAME)
    resp = await client.delete("/api/v1/sectors/cache", headers=headers)
    assert resp.status_code == 200 and resp.json()["cleared"] == 1
    stats = (
        await client.get("/api/v1/sectors/cache/stats", headers=headers)
    ).json()
    assert stats["entries"] == 0


async def test_cache_flush_disabled_without_admin(client, monkeypatch):
    # The demo account is public — with ADMIN_USERNAME unset nobody flushes.
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "")
    headers = await _login(client)
    resp = await client.delete("/api/v1/sectors/cache", headers=headers)
    assert resp.status_code == 403


async def test_cache_flush_rejects_non_admin(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "someone-else")
    headers = await _login(client)
    resp = await client.delete("/api/v1/sectors/cache", headers=headers)
    assert resp.status_code == 403
