"""Sectors API tools — LangChain wrappers over the credit-aware cache.

Every call flows through `cached_get`, so repeated or equivalent questions
cost zero credits. Defaults are credit-minimal: explicit sections/periods on
per-part-billed endpoints, structured screener over the 3-credit natural
language mode, and small result windows.

Each tool returns a JSON envelope: {status, source, stale, fetched_at,
now_wib, data}. `stale=true` means newer data likely exists — the agent
decides and retries with refresh=True. Symbols are validated before any
upstream call so malformed tickers never burn a paid 404.
"""

import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from langchain_core.tools import tool

from app.core.config import settings
from app.sectors import cache, client
from app.sectors.freshness import WIB, Freshness

_SYMBOL_RE = re.compile(r"^[A-Z]{4}$")
_SYMBOL_OR_INDEX_RE = re.compile(r"^([A-Z]{4}|IHSG)$")
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")

_COMPANY_SECTIONS = {
    "overview", "valuation", "future", "peers",
    "financials", "dividend", "management", "ownership",
}
_SUBSECTOR_SECTIONS = {
    "statistics", "market_cap", "stability",
    "valuation", "growth", "companies",
}
_MOVER_CLASSES = {"top_gainers", "top_losers"}
_MOVER_PERIODS = {"1d", "7d", "14d", "30d", "365d"}
_ACTION_TYPES = {
    "agm", "bonus", "dividend", "right_issue",
    "stock_split", "upcoming_dividend", "warrant",
}
_BROKER_COHORTS = {"all", "institutional", "mixed", "retail", "unknown"}


def _err(msg: str, **extra: Any) -> str:
    return json.dumps({"error": msg, **extra})


def _render(res: cache.CacheResult) -> str:
    envelope: dict[str, Any] = {
        "status": res.status,
        "source": res.source,
        "stale": res.stale,
        "fetched_at": res.fetched_at,
        "now_wib": datetime.now(WIB).isoformat(timespec="seconds"),
        "data": res.data,
    }
    out = json.dumps(envelope, default=str)
    if len(out) <= settings.SECTORS_TOOL_MAX_CHARS:
        return out
    # Keep the envelope valid: demote oversized data to a truncated string.
    budget = max(settings.SECTORS_TOOL_MAX_CHARS - 400, 1000)
    envelope["data"] = json.dumps(res.data, default=str)[:budget] + "…"
    envelope["truncated"] = True
    return json.dumps(envelope, default=str)


async def _call(
    endpoint: str,
    path: str,
    params: dict[str, Any],
    freshness: Freshness,
    credits: int = 1,
    refresh: bool = False,
) -> str:
    try:
        res = await cache.cached_get(
            endpoint, path, params, freshness, credits=credits, refresh=refresh
        )
    except client.SectorsUnavailable as exc:
        return _err("sectors_api_unavailable", detail=str(exc))
    return _render(res)


def _norm_symbol(symbol: str, allow_index: bool = False) -> str | None:
    s = symbol.strip().upper().removesuffix(".JK")
    pattern = _SYMBOL_OR_INDEX_RE if allow_index else _SYMBOL_RE
    return s if pattern.match(s) else None


def _norm_slug(slug: str) -> str | None:
    s = slug.strip().lower()
    return s if _SLUG_RE.match(s) else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value.strip())  # raises ValueError


def _window(start: str | None, end: str | None, days: int) -> tuple[str, str] | str:
    """Resolve (start, end) with defaults; clamps to a `days`-wide window."""
    try:
        end_d = _parse_date(end) or datetime.now(WIB).date()
        start_d = _parse_date(start) or end_d - timedelta(days=days)
    except ValueError:
        return "invalid_date — use YYYY-MM-DD"
    if (end_d - start_d).days > days:
        start_d = end_d - timedelta(days=days)
    return str(start_d), str(end_d)


def _pick(values: list[str], allowed: set[str], default: list[str]) -> list[str]:
    """Filter to allowed values, dedup + sort (canonical for the cache key)."""
    picked = sorted({v.strip().lower() for v in values} & allowed)
    return picked or default


@tool
async def sectors_screen(
    where: str | None = None,
    order_by: str = "market_cap",
    desc: bool = True,
    limit: int = 10,
    q: str | None = None,
    refresh: bool = False,
) -> str:
    """Screen IDX-listed companies by fundamentals, valuation, tags, or
    indices. Prefer `where` + `order_by` (SQL-like, e.g. "sector = 'Financials'
    and roe_ttm > 0.15"; yearly fields use bracket notation like
    revenue[2024]) — costs 1 credit. `q` is natural language and costs 3
    credits — only when `where` can't express the request. Each page is a
    billed call, so keep `limit` small.

    Args:
        where: SQL-like filter expression (structured mode).
        order_by: Field to sort by.
        desc: Sort descending.
        limit: Rows per page (max 50).
        q: Natural-language query (3 credits; overrides `where`).
        refresh: Bypass the cache and fetch fresh data.
    """
    params: dict[str, Any] = {
        "order_by": order_by,
        "desc": desc,
        "limit": max(1, min(limit, 50)),
    }
    credits = 1
    if q:
        params["q"] = q
        credits = 3
    elif where:
        params["where"] = where
    return await _call(
        "screen", "/v2/companies/", params, Freshness.EOD, credits, refresh
    )


@tool
async def sectors_company_report(
    symbol: str,
    sections: list[str] = ["overview"],
    refresh: bool = False,
) -> str:
    """Comprehensive report for one IDX ticker. Billed PER SECTION — request
    only what the question needs: overview (identity, market cap, price,
    ESG, tags), valuation (PE/PB/PS/intrinsic), financials (annual
    statements), peers, dividend, future (analyst estimates), management,
    ownership. All 8 sections cost 8 credits.

    Args:
        symbol: IDX ticker, e.g. BBCA, TLKM.
        sections: Report sections to include.
        refresh: Bypass the cache and fetch fresh data.
    """
    sym = _norm_symbol(symbol)
    if not sym:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
    chosen = _pick(sections, _COMPANY_SECTIONS, ["overview"])
    return await _call(
        "company_report", f"/v2/company/report/{sym}/",
        {"sections": ",".join(chosen)}, Freshness.EOD, len(chosen), refresh,
    )


@tool
async def sectors_subsector_report(
    sub_sector: str,
    sections: list[str] = ["statistics"],
    refresh: bool = False,
) -> str:
    """Aggregate report for one IDX subsector. Billed PER SECTION — request
    only what you need: statistics (counts, PE range), market_cap, stability
    (drawdown), valuation, growth, companies (member list). All 6 = 6 credits.
    Get valid slugs from sectors_list_subsectors.

    Args:
        sub_sector: Kebab-case slug, e.g. banks, food-beverage.
        sections: Report sections to include.
        refresh: Bypass the cache and fetch fresh data.
    """
    slug = _norm_slug(sub_sector)
    if not slug:
        return _err("invalid_sub_sector", sub_sector=sub_sector, hint="kebab-case slug, e.g. banks")
    chosen = _pick(sections, _SUBSECTOR_SECTIONS, ["statistics"])
    return await _call(
        "subsector_report", f"/v2/subsector/report/{slug}/",
        {"sections": ",".join(chosen)}, Freshness.EOD, len(chosen), refresh,
    )


@tool
async def sectors_top_movers(
    classifications: list[str] = ["top_gainers", "top_losers"],
    periods: list[str] = ["1d"],
    n_stock: int = 5,
    sub_sector: str | None = None,
    refresh: bool = False,
) -> str:
    """Top gainers and losers. Billed per classification × period — the
    upstream default (2 × 5) costs 10 credits, so pass only what the question
    needs.

    Args:
        classifications: top_gainers and/or top_losers.
        periods: 1d, 7d, 14d, 30d, or 365d.
        n_stock: Companies per period (max 10).
        sub_sector: Optional kebab-case subsector filter.
        refresh: Bypass the cache and fetch fresh data.
    """
    cls = _pick(classifications, _MOVER_CLASSES, ["top_gainers"])
    per = _pick(periods, _MOVER_PERIODS, ["1d"])
    params: dict[str, Any] = {
        "classifications": ",".join(cls),
        "periods": ",".join(per),
        "n_stock": max(1, min(n_stock, 10)),
    }
    if sub_sector and (slug := _norm_slug(sub_sector)):
        params["sub_sector"] = slug
    return await _call(
        "top_movers", "/v2/companies/top-changes/", params,
        Freshness.EOD, len(cls) * len(per), refresh,
    )


@tool
async def sectors_daily_prices(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    refresh: bool = False,
) -> str:
    """Daily OHLC close, volume, and market cap for one IDX ticker over a
    max 90-day window (defaults: last 30 days). 1 credit. Windows fully in
    the past are immutable and cached permanently.

    Args:
        symbol: IDX ticker, e.g. BBCA, GOTO.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        refresh: Bypass the cache and fetch fresh data.
    """
    sym = _norm_symbol(symbol)
    if not sym:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
    window = _window(start, end, 90)
    if isinstance(window, str):
        return _err(window)
    return await _call(
        "daily", f"/v2/daily/{sym}/",
        {"start": window[0], "end": window[1]}, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_most_traded(
    start: str | None = None,
    end: str | None = None,
    n_stock: int = 5,
    sub_sector: str | None = None,
    adjusted: bool = False,
    refresh: bool = False,
) -> str:
    """Most traded IDX stocks by volume per day, keyed by date (max 90-day
    window, defaults to last 30 days). 2 credits.

    Args:
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        n_stock: Tickers per day (max 10).
        sub_sector: Optional kebab-case subsector filter.
        adjusted: Rank by volume × price instead of raw volume.
        refresh: Bypass the cache and fetch fresh data.
    """
    window = _window(start, end, 90)
    if isinstance(window, str):
        return _err(window)
    params: dict[str, Any] = {
        "start": window[0], "end": window[1],
        "n_stock": max(1, min(n_stock, 10)), "adjusted": adjusted,
    }
    if sub_sector and (slug := _norm_slug(sub_sector)):
        params["sub_sector"] = slug
    return await _call("most_traded", "/v2/most-traded/", params, Freshness.EOD, 2, refresh)


@tool
async def sectors_idx_market_summary(
    start: str | None = None,
    end: str | None = None,
    refresh: bool = False,
) -> str:
    """Total IDX market capitalization per day (max 90-day window, defaults
    to last 30 days; data starts 2021-01-01). 1 credit.

    Args:
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        refresh: Bypass the cache and fetch fresh data.
    """
    window = _window(start, end, 90)
    if isinstance(window, str):
        return _err(window)
    return await _call(
        "idx_total", "/v2/idx-total/",
        {"start": window[0], "end": window[1]}, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_foreign_flow(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    refresh: bool = False,
) -> str:
    """Daily net foreign-investor inflow (IDR) for one IDX ticker — positive
    means foreigners were net buyers. Pass IHSG for the market-wide series.
    Max 90-day window, defaults to last 30 days. 1 credit.

    Args:
        symbol: IDX ticker or IHSG for market-wide flow.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        refresh: Bypass the cache and fetch fresh data.
    """
    sym = _norm_symbol(symbol, allow_index=True)
    if not sym:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, or IHSG")
    window = _window(start, end, 90)
    if isinstance(window, str):
        return _err(window)
    return await _call(
        "foreign_flow", f"/v2/foreign-flow/{sym}/",
        {"start": window[0], "end": window[1]}, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_quarterly_financials(
    symbol: str,
    n_quarters: int = 2,
    report_date: str | None = None,
    refresh: bool = False,
) -> str:
    """Quarterly financial statements for one IDX ticker (banks include
    loan/deposit metrics). Billed per quarter returned — keep n_quarters
    small.

    Args:
        symbol: IDX ticker, e.g. BMRI, BBCA.
        n_quarters: Most recent quarters to return (max 8).
        report_date: Specific report date YYYY-MM-DD (approximate match).
        refresh: Bypass the cache and fetch fresh data.
    """
    sym = _norm_symbol(symbol)
    if not sym:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
    params: dict[str, Any] = {"approx": True}
    n = max(1, min(n_quarters, 8))
    if report_date:
        try:
            params["report_date"] = str(_parse_date(report_date))
        except ValueError:
            return _err("invalid_date — use YYYY-MM-DD")
    else:
        params["n_quarters"] = n
    return await _call(
        "quarterly_financials", f"/v2/financials/quarterly/{sym}/",
        params, Freshness.EOD, n if "n_quarters" in params else 1, refresh,
    )


@tool
async def sectors_list_subsectors(refresh: bool = False) -> str:
    """All IDX sector/subsector slug pairs — the valid inputs for
    sub_sector parameters on other tools. Reference data, cached for days.
    1 credit.

    Args:
        refresh: Bypass the cache and fetch fresh data.
    """
    return await _call("subsectors", "/v2/subsectors/", {}, Freshness.STATIC, 1, refresh)


@tool
async def sectors_news(
    symbols: str | None = None,
    sub_sector: str | None = None,
    keyword: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 10,
    refresh: bool = False,
) -> str:
    """IDX news articles filtered by tickers, subsector, or title keyword.
    Updates intraday — cached entries are only held for minutes. 1 credit.

    Args:
        symbols: Comma-separated IDX tickers, e.g. "BBCA,BBRI".
        sub_sector: Comma-separated kebab-case subsector slugs.
        keyword: Case-insensitive title substring.
        start: Start date YYYY-MM-DD (optional lower bound).
        end: End date YYYY-MM-DD (optional upper bound; future dates 400).
        limit: Articles per page (max 30).
        refresh: Bypass the cache and fetch fresh data.
    """
    params: dict[str, Any] = {"extension": "idx", "limit": max(1, min(limit, 30))}
    if symbols:
        params["symbols"] = ",".join(
            sorted(s.strip().upper().removesuffix(".JK") for s in symbols.split(","))
        )
    if sub_sector:
        params["sub_sector"] = ",".join(
            sorted(s.strip().lower() for s in sub_sector.split(","))
        )
    if keyword:
        params["keyword"] = keyword.strip()
    try:
        if start:
            params["start"] = str(_parse_date(start))
        if end:
            params["end"] = str(_parse_date(end))
    except ValueError:
        return _err("invalid_date — use YYYY-MM-DD")
    return await _call("news", "/v2/news/", params, Freshness.NEWS, 1, refresh)


@tool
async def sectors_broker_summary(
    symbol: str,
    broker_code: str | None = None,
    start: str | None = None,
    end: str | None = None,
    refresh: bool = False,
) -> str:
    """Per-broker daily trading rows for one IDX ticker (max 14-day window,
    defaults to last 14 days) — buy/sell/net values plus the foreign split.
    1 credit.

    Args:
        symbol: IDX ticker, e.g. BBCA.
        broker_code: Optional single broker filter, e.g. MG.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        refresh: Bypass the cache and fetch fresh data.
    """
    sym = _norm_symbol(symbol)
    if not sym:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
    window = _window(start, end, 14)
    if isinstance(window, str):
        return _err(window)
    params: dict[str, Any] = {"start": window[0], "end": window[1]}
    if broker_code:
        params["broker_code"] = broker_code.strip().upper()
    return await _call(
        "broker_summary", f"/v2/broker-summary/{sym}/",
        params, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_broker_top(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    cohort: str = "all",
    foreign: bool = False,
    refresh: bool = False,
) -> str:
    """Brokers most actively accumulating and distributing one IDX ticker —
    top_buyers and top_sellers by net value, with the foreign-investor
    portion. Max 90-day window, defaults to last 30 days. 2 credits.

    Args:
        symbol: IDX ticker, e.g. BBCA.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        cohort: all, institutional, mixed, retail, or unknown.
        foreign: Rank by foreign net flow instead of total.
        refresh: Bypass the cache and fetch fresh data.
    """
    sym = _norm_symbol(symbol)
    if not sym:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
    window = _window(start, end, 90)
    if isinstance(window, str):
        return _err(window)
    c = cohort.strip().lower()
    if c not in _BROKER_COHORTS:
        return _err("invalid_cohort", cohort=cohort, allowed=sorted(_BROKER_COHORTS))
    params = {"start": window[0], "end": window[1], "cohort": c, "foreign": foreign}
    return await _call(
        "broker_top", f"/v2/broker-summary/{sym}/top/",
        params, Freshness.EOD, 2, refresh,
    )


@tool
async def sectors_insider_filings(
    symbol: str | None = None,
    sub_sector: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 10,
    refresh: bool = False,
) -> str:
    """IDX insider-trading filings — buy/sell transactions by insiders and
    major shareholders. 1 credit per page.

    Args:
        symbol: Optional IDX ticker filter.
        sub_sector: Optional kebab-case subsector filter.
        start: Start date YYYY-MM-DD (optional lower bound).
        end: End date YYYY-MM-DD (optional upper bound).
        limit: Results per page (max 30).
        refresh: Bypass the cache and fetch fresh data.
    """
    params: dict[str, Any] = {"limit": max(1, min(limit, 30))}
    if symbol:
        sym = _norm_symbol(symbol)
        if not sym:
            return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
        params["symbol"] = sym
    if sub_sector and (slug := _norm_slug(sub_sector)):
        params["sub_sector"] = slug
    try:
        if start:
            params["start"] = str(_parse_date(start))
        if end:
            params["end"] = str(_parse_date(end))
    except ValueError:
        return _err("invalid_date — use YYYY-MM-DD")
    return await _call("filings", "/v2/filings/", params, Freshness.NEWS, 1, refresh)


@tool
async def sectors_suspensions(
    symbol: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 10,
    refresh: bool = False,
) -> str:
    """Historical IDX stock suspensions with the official reason and IDX
    notice link. 1 credit per page.

    Args:
        symbol: Optional IDX ticker filter.
        start: Start date YYYY-MM-DD (optional lower bound).
        end: End date YYYY-MM-DD (optional upper bound).
        limit: Results per page (max 30).
        refresh: Bypass the cache and fetch fresh data.
    """
    params: dict[str, Any] = {"limit": max(1, min(limit, 30))}
    if symbol:
        sym = _norm_symbol(symbol)
        if not sym:
            return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
        params["symbol"] = sym
    try:
        if start:
            params["start"] = str(_parse_date(start))
        if end:
            params["end"] = str(_parse_date(end))
    except ValueError:
        return _err("invalid_date — use YYYY-MM-DD")
    return await _call(
        "suspensions", "/v2/suspensions/", params, Freshness.NEWS, 1, refresh
    )


@tool
async def sectors_corporate_actions(
    types: list[str] = ["dividend", "upcoming_dividend"],
    start: str | None = None,
    end: str | None = None,
    refresh: bool = False,
) -> str:
    """Market-wide corporate actions calendar, grouped by type. Billed PER
    TYPE — the upstream default (all 7) costs 7 credits, so request only the
    types needed. `end` may be future; default window is ±30 days around
    today.

    Args:
        types: dividend, upcoming_dividend, bonus, right_issue, stock_split,
            warrant, agm.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD (may be future — it's a calendar).
        refresh: Bypass the cache and fetch fresh data.
    """
    chosen = _pick(types, _ACTION_TYPES, ["dividend"])
    today = datetime.now(WIB).date()
    try:
        end_d = _parse_date(end) or today + timedelta(days=30)
        start_d = _parse_date(start) or end_d - timedelta(days=30)
    except ValueError:
        return _err("invalid_date — use YYYY-MM-DD")
    params = {"start": str(start_d), "end": str(end_d), "type": ",".join(chosen)}
    return await _call(
        "corporate_actions", "/v2/corporate-actions/",
        params, Freshness.EOD, len(chosen), refresh,
    )


@tool
async def sectors_listing_performance(
    symbol: str,
    refresh: bool = False,
) -> str:
    """IPO/listing performance for one IDX ticker — price change since
    listing across 7/30/90/365-day windows plus offering details. Only covers
    tickers listed after May 2005. 1 credit.

    Args:
        symbol: IDX ticker, e.g. BREN, GOTO.
        refresh: Bypass the cache and fetch fresh data.
    """
    sym = _norm_symbol(symbol)
    if not sym:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BREN")
    return await _call(
        "listing_performance", f"/v2/listing-performance/{sym}/",
        {}, Freshness.EOD, 1, refresh,
    )


TOOLS = [
    sectors_screen,
    sectors_company_report,
    sectors_subsector_report,
    sectors_top_movers,
    sectors_daily_prices,
    sectors_most_traded,
    sectors_idx_market_summary,
    sectors_foreign_flow,
    sectors_quarterly_financials,
    sectors_list_subsectors,
    sectors_news,
    sectors_broker_summary,
    sectors_broker_top,
    sectors_insider_filings,
    sectors_suspensions,
    sectors_corporate_actions,
    sectors_listing_performance,
]
