"""Raw Sectors reads for the aksi pipeline.

The LangChain tools truncate payloads to fit an LLM context; the calculators
need complete rows (a market-wide 90-day calendar easily exceeds the budget).
These readers send exactly the same path + params as the matching tools — so
the permanent cache is shared with the chat agent — but return the full
envelope as a dict.
"""

from datetime import datetime, timezone
from typing import Any

from app.sectors import cache, client
from app.sectors.freshness import WIB, Freshness


def _not_future(day: str) -> str:
    """Upstream validates `end` against UTC today — clamp like the tools do."""
    return min(day, datetime.now(timezone.utc).date().isoformat())


async def _get(endpoint: str, path: str, params: dict[str, Any],
               freshness: Freshness, credits: int) -> dict:
    try:
        res = await cache.cached_get(endpoint, path, params, freshness, credits=credits)
    except client.SectorsUnavailable as exc:
        return {"error": "sectors_api_unavailable", "detail": str(exc)}
    return {"status": res.status, "source": res.source, "stale": res.stale,
            "fetched_at": res.fetched_at, "data": res.data}


async def calendar(types: list[str], start: str, end: str) -> dict:
    chosen = sorted(set(types))
    return await _get("corporate_actions", "/v2/corporate-actions/",
                      {"start": start, "end": end, "type": ",".join(chosen)},
                      Freshness.EOD, len(chosen))


async def daily_prices(symbol: str, start: str, end: str) -> dict:
    return await _get("daily", f"/v2/daily/{symbol}/",
                      {"start": start, "end": _not_future(end)}, Freshness.EOD, 1)


async def insider_filings(symbol: str, start: str, end: str, limit: int = 30) -> dict:
    return await _get("filings", "/v2/filings/",
                      {"limit": limit, "symbol": symbol, "start": start, "end": _not_future(end)},
                      Freshness.NEWS, 1)


async def shareholders(symbol: str, year: int) -> dict:
    current = datetime.now(WIB).year
    freshness = Freshness.HISTORICAL if year < current else Freshness.EOD
    return await _get("shareholders", f"/v2/company/shareholders-composition/{symbol}/",
                      {"year": year}, freshness, 1)


async def company_report(symbol: str, sections: list[str]) -> dict:
    chosen = sorted(set(sections))
    return await _get("company_report", f"/v2/company/report/{symbol}/",
                      {"sections": ",".join(chosen)}, Freshness.EOD, len(chosen))
