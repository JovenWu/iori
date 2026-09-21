"""Permanent, credit-aware response cache for the Sectors API.

Every upstream call costs credits, so responses are cached globally and kept
forever — staleness is computed on read and surfaced to the agent as a hint;
the agent overrides via `refresh=True`. Identical in-flight requests are
single-flighted so concurrent tool calls share one upstream fetch, and an
upstream failure falls back to the stored entry rather than failing the turn.
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session_maker
from app.models.sectors_cache import SectorsCache
from app.sectors import client
from app.sectors.freshness import Freshness, classify, is_stale

logger = logging.getLogger(__name__)

# Statuses that consume a credit — worth persisting. 400/401/403/429/5xx are
# free per Sectors billing, so they pass through but are never stored.
_BILLABLE = {200, 404}

_inflight: dict[str, asyncio.Task] = {}


@dataclass
class CacheResult:
    status: int
    data: Any
    source: str  # "hit" | "upstream" | "stale_fallback"
    fetched_at: str  # ISO timestamp of the upstream fetch
    stale: bool  # deterministic hint — agent decides whether to refresh


def cache_key(path: str, params: dict[str, Any]) -> str:
    """sha256 of path + canonical params (key order and list order normalized
    so equivalent requests share one entry). Path carries the endpoint and any
    path params (e.g. the symbol), so distinct symbols never collide."""
    canon = {
        k: sorted(str(v) for v in val) if isinstance(val, (list, tuple)) else val
        for k, val in (params or {}).items()
    }
    raw = f"{path}|{json.dumps(canon, sort_keys=True, default=str)}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _read(key: str) -> SectorsCache | None:
    async with async_session_maker() as db:
        return await db.get(SectorsCache, key)


async def _bump_hits(key: str) -> None:
    async with async_session_maker() as db:
        await db.execute(
            update(SectorsCache)
            .where(SectorsCache.id == key)
            .values(hits=SectorsCache.hits + 1)
        )
        await db.commit()


async def _store(
    key: str,
    endpoint: str,
    params: dict[str, Any],
    status: int,
    data: Any,
    freshness: Freshness,
    credits: int,
    now: datetime,
) -> None:
    async with async_session_maker() as db:
        row = await db.get(SectorsCache, key)
        if row is None:
            db.add(
                SectorsCache(
                    id=key,
                    endpoint=endpoint,
                    freshness=freshness.value,
                    params=params,
                    status=status,
                    payload=data,
                    credits=credits,
                    fetched_at=now,
                )
            )
        else:
            row.freshness = freshness.value
            row.params = params
            row.status = status
            row.payload = data
            row.credits = credits
            row.fetched_at = now
        try:
            await db.commit()
        except IntegrityError:
            # Raced insert from another process — same key means same request,
            # so the winner's row is equivalent. Keep `hits` cumulative either way.
            await db.rollback()


async def cached_get(
    endpoint: str,
    path: str,
    params: dict[str, Any] | None,
    freshness: Freshness,
    *,
    credits: int = 1,
    refresh: bool = False,
) -> CacheResult:
    """Read-through cache for one upstream GET.

    `credits` is the known upstream cost of this call, stored so the stats
    endpoint can report credits saved rather than bare hit count.
    """
    params = params or {}
    key = cache_key(path, params)
    now = datetime.now(timezone.utc)

    existing = await _read(key)
    if existing is not None and not refresh:
        await _bump_hits(key)
        return CacheResult(
            existing.status,
            existing.payload,
            "hit",
            existing.fetched_at.isoformat(),
            is_stale(existing.freshness, existing.fetched_at, now),
        )

    # Miss or forced refresh — single-flight the upstream call.
    task = _inflight.get(key)
    owner = task is None
    if owner:
        task = asyncio.create_task(client.get(path, params))
        _inflight[key] = task
    try:
        status, data = await asyncio.shield(task)
    except client.SectorsUnavailable:
        if existing is not None:
            return CacheResult(
                existing.status,
                existing.payload,
                "stale_fallback",
                existing.fetched_at.isoformat(),
                True,
            )
        raise
    finally:
        if task.done():
            _inflight.pop(key, None)

    # A failed refresh (429/5xx — free but useless) shouldn't surface as an
    # error when a stored entry can answer instead.
    if status not in _BILLABLE and existing is not None:
        return CacheResult(
            existing.status,
            existing.payload,
            "stale_fallback",
            existing.fetched_at.isoformat(),
            True,
        )

    if owner and status in _BILLABLE:
        await _store(
            key, endpoint, params, status, data,
            classify(freshness, params, now), credits, now,
        )
    return CacheResult(status, data, "upstream", now.isoformat(), False)


async def cache_stats() -> dict[str, Any]:
    """Aggregate for the stats endpoint: hits × credits = credits saved."""
    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(
                    SectorsCache.endpoint,
                    SectorsCache.hits,
                    SectorsCache.credits,
                    SectorsCache.fetched_at,
                )
            )
        ).all()
    by_endpoint: dict[str, dict[str, int]] = {}
    for endpoint, hits, credits, _fetched_at in rows:
        agg = by_endpoint.setdefault(endpoint, {"entries": 0, "hits": 0, "credits_saved": 0})
        agg["entries"] += 1
        agg["hits"] += hits
        agg["credits_saved"] += hits * credits
    return {
        "entries": len(rows),
        "total_hits": sum(r[1] for r in rows),
        "credits_saved": sum(r[1] * r[2] for r in rows),
        "by_endpoint": by_endpoint,
    }


async def cache_clear() -> int:
    async with async_session_maker() as db:
        result = await db.execute(delete(SectorsCache))
        await db.commit()
        return result.rowcount or 0
