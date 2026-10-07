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

import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from langchain_core.tools import tool

from app.core.config import settings
from app.sectors import cache, client
from app.sectors.freshness import WIB, Freshness, last_refresh_boundary

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
_BROKER_CODE_RE = re.compile(r"^[A-Z]{2}$")
_BROKER_ORIGINS = {"domestic", "foreign"}
_TOP_BROKER_METRICS = {"gross", "net"}
_INDEX_CODES = {
    "ftse", "idx30", "idxbumn20", "idxesgl", "idxg30", "idxhidiv20",
    "idxq30", "idxv30", "ihsg", "jii70", "kompas100", "lq45",
    "sminfra18", "srikehati", "sti", "economic30", "idxvesta28",
}
_FLOW_ORDER = {
    "net_foreign_inflow", "-net_foreign_inflow",
    "foreign_buy_idr", "-foreign_buy_idr",
    "foreign_sell_idr", "-foreign_sell_idr",
    "symbol", "-symbol",
}
_SHAREHOLDERS_FIRST_YEAR = 2021
_COMPARE_MAX_SYMBOLS = 8


def _err(msg: str, **extra: Any) -> str:
    return json.dumps({"error": msg, **extra})


def _compact(node: Any) -> Any:
    """Drop null fields recursively — they carry no information."""
    if isinstance(node, dict):
        return {k: _compact(v) for k, v in node.items() if v is not None}
    if isinstance(node, list):
        return [_compact(x) for x in node]
    return node


def _halve_rows(node: Any) -> Any:
    """Keep the tail half of every embedded list-of-dicts — for the
    chronological series these tools return, that's the newest rows."""
    if isinstance(node, dict):
        return {k: _halve_rows(v) for k, v in node.items()}
    if isinstance(node, list):
        if node and all(isinstance(x, dict) for x in node):
            return node[max(1, len(node) // 2):]
        return [_halve_rows(x) for x in node]
    return node


def _shrink(data: Any, budget: int) -> Any:
    """Strip nulls, then halve row-lists until the data fits `budget` —
    keeps `data` valid JSON so charts still extract from the newest rows."""
    data = _compact(data)
    for _ in range(8):
        if len(json.dumps(data, default=str)) <= budget:
            break
        shrunk = _halve_rows(data)
        if shrunk == data:
            break
        data = shrunk
    return data


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
    # Over budget: strip nulls and drop oldest rows so `data` stays valid
    # JSON — only payloads with no rows to trim get flattened to a string.
    budget = max(settings.SECTORS_TOOL_MAX_CHARS - 400, 1000)
    envelope["data"] = _shrink(res.data, budget)
    envelope["truncated"] = True
    out = json.dumps(envelope, default=str)
    if len(out) <= settings.SECTORS_TOOL_MAX_CHARS:
        return out
    envelope["data"] = json.dumps(envelope["data"], default=str)[:budget] + "…"
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


def _norm_symbols(
    raw: str, allow_index: bool = False, cap: int = _COMPARE_MAX_SYMBOLS
) -> list[str]:
    """Comma-separated tickers → normalized, deduped, order-preserving."""
    return list(dict.fromkeys(
        s for s in (_norm_symbol(p, allow_index=allow_index)
                    for p in raw.split(","))
        if s
    ))[:cap]


async def _fanout(
    endpoint: str,
    path_fmt: str,
    params: dict[str, Any],
    freshness: Freshness,
    credits: int,
    refresh: bool,
    syms: list[str],
) -> str:
    """One upstream GET per symbol, in parallel → a single envelope whose
    `data` is a {symbol: sub-envelope} map — the shape comparison chart
    extractors pivot into multi-series specs."""

    async def _one(sym: str) -> tuple[str, dict]:
        try:
            res = await cache.cached_get(
                endpoint, path_fmt.format(sym), params,
                freshness, credits=credits, refresh=refresh,
            )
            return sym, {
                "status": res.status, "source": res.source,
                "stale": res.stale, "fetched_at": res.fetched_at,
                "data": res.data,
            }
        except client.SectorsUnavailable as exc:
            return sym, {"error": "sectors_api_unavailable", "detail": str(exc)}

    data = dict(await asyncio.gather(*(_one(s) for s in syms)))
    ok = [v for v in data.values() if v.get("status") == 200]
    res = cache.CacheResult(
        status=200 if ok else int(next(iter(data.values())).get("status") or 502),
        data=data,
        source=(
            "hit"
            if ok and all(v.get("source") == "hit" for v in data.values())
            else "upstream"
        ),
        fetched_at=max(v.get("fetched_at", "") for v in data.values()),
        stale=any(v.get("stale") for v in data.values()),
    )
    return _render(res)


def _norm_slug(slug: str) -> str | None:
    s = slug.strip().lower()
    return s if _SLUG_RE.match(s) else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value.strip())  # raises ValueError


def _window(start: str | None, end: str | None, days: int) -> tuple[str, str] | str:
    """Resolve (start, end) with defaults; clamps to a `days`-wide window.

    Unset `end` defaults to the last EOD publication boundary date (WIB), not
    the wall clock — the rows upstream returns are identical, but the cache
    key stays stable for the whole data-day instead of rolling daily, and the
    entry classifies as HISTORICAL (never stale). An explicit `end` can't
    exceed the API's "today" — upstream validates it against UTC, so between
    WIB midnight and 07:00 a WIB-today end is a future date upstream (400).
    `start` must not be after `end` — checked locally so a bad window never
    burns a request."""
    now = datetime.now(timezone.utc)
    today = now.date()
    try:
        end_d = _parse_date(end) or last_refresh_boundary(now).date()
        start_d = _parse_date(start) or end_d - timedelta(days=days)
    except ValueError:
        return "invalid_date — use YYYY-MM-DD"
    if end_d > today:
        end_d = today
    if start_d > end_d:
        return "invalid_date — start must not be after end"
    if (end_d - start_d).days > days:
        start_d = end_d - timedelta(days=days)
    return str(start_d), str(end_d)


def _pick(values: list[str], allowed: set[str], default: list[str]) -> list[str]:
    """Filter to allowed values, dedup + sort (canonical for the cache key)."""
    picked = sorted({v.strip().lower() for v in values} & allowed)
    return picked or default


def _norm_broker(code: str) -> str | None:
    c = code.strip().upper()
    return c if _BROKER_CODE_RE.match(c) else None


def _norm_index(code: str) -> str | None:
    c = code.strip().lower()
    return c if c in _INDEX_CODES else None


def _single_day(value: str | None) -> tuple[str | None, str | None]:
    """Single-day params → (date_str, error). Future dates 400 upstream —
    still free, but a local rejection carries a clearer message."""
    if not value:
        return None, None
    try:
        d = date.fromisoformat(value.strip())
    except ValueError:
        return None, "invalid_date — use YYYY-MM-DD"
    if d > datetime.now(timezone.utc).date():
        return None, "invalid_date — future dates have no data yet"
    return str(d), None


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
        "include_query_values": True,
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
    """Daily OHLC close, volume, and market cap for IDX tickers over a max
    90-day window (defaults: last 30 days). Pass comma-separated tickers
    ("BBCA,BBRI") to compare — one call fans out and returns a
    {symbol: envelope} map that charts as indexed (base-100) lines. 1 credit
    per symbol. Windows fully in the past are immutable and cached
    permanently.

    Args:
        symbol: IDX ticker, e.g. BBCA, GOTO — or a comma-separated list.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        refresh: Bypass the cache and fetch fresh data.
    """
    syms = _norm_symbols(symbol)
    if not syms:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
    window = _window(start, end, 90)
    if isinstance(window, str):
        return _err(window)
    params = {"start": window[0], "end": window[1]}
    if len(syms) == 1:
        return await _call(
            "daily", f"/v2/daily/{syms[0]}/", params, Freshness.EOD, 1, refresh,
        )
    return await _fanout(
        "daily", "/v2/daily/{}/", params, Freshness.EOD, 1, refresh, syms
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
    """Daily net foreign-investor inflow (IDR) — positive means foreigners
    were net buyers. Pass IHSG for the market-wide series, or comma-separated
    tickers ("BBCA,BBRI") to compare — multi-symbol calls fan out in one step
    and return a {symbol: envelope} map that charts as one multi-line
    comparison. Max 90-day window, defaults to the last 90 days. 1 credit per
    symbol.

    Args:
        symbol: IDX ticker(s), or IHSG for market-wide flow.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        refresh: Bypass the cache and fetch fresh data.
    """
    syms = _norm_symbols(symbol, allow_index=True)
    if not syms:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, or IHSG")
    window = _window(start, end, 90)
    if isinstance(window, str):
        return _err(window)
    params = {"start": window[0], "end": window[1]}
    if len(syms) == 1:
        return await _call(
            "foreign_flow", f"/v2/foreign-flow/{syms[0]}/",
            params, Freshness.EOD, 1, refresh,
        )
    return await _fanout(
        "foreign_flow", "/v2/foreign-flow/{}/",
        params, Freshness.EOD, 1, refresh, syms,
    )


@tool
async def sectors_quarterly_financials(
    symbol: str,
    n_quarters: int = 2,
    report_date: str | None = None,
    refresh: bool = False,
) -> str:
    """Quarterly financial statements for IDX tickers (banks include
    loan/deposit metrics). Pass comma-separated tickers ("BBCA,BMRI") to
    compare — one call fans out and returns a {symbol: envelope} map that
    charts as revenue+earnings lines per ticker. Billed per quarter per
    symbol — keep n_quarters small.

    Args:
        symbol: IDX ticker, e.g. BMRI, BBCA — or a comma-separated list.
        n_quarters: Most recent quarters to return (max 8).
        report_date: Specific report date YYYY-MM-DD (approximate match).
        refresh: Bypass the cache and fetch fresh data.
    """
    syms = _norm_symbols(symbol)
    if not syms:
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
    credits = n if "n_quarters" in params else 1
    if len(syms) == 1:
        return await _call(
            "quarterly_financials", f"/v2/financials/quarterly/{syms[0]}/",
            params, Freshness.EOD, credits, refresh,
        )
    return await _fanout(
        "quarterly_financials", "/v2/financials/quarterly/{}/",
        params, Freshness.EOD, credits, refresh, syms,
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


@tool
async def sectors_company_segments(
    symbol: str,
    financial_year: int | None = None,
    refresh: bool = False,
) -> str:
    """Revenue and cost segment breakdown for one IDX ticker — Sankey-ready
    source/target rows showing what actually drives the business. Not every
    company has segment data; sectors_companies_with_segments lists those
    that do. 1 credit.

    Args:
        symbol: IDX ticker, e.g. ASII, BUMI.
        financial_year: Optional year, e.g. 2024. Defaults to latest available.
        refresh: Bypass the cache and fetch fresh data.
    """
    sym = _norm_symbol(symbol)
    if not sym:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. ASII")
    params: dict[str, Any] = {}
    freshness = Freshness.EOD
    if financial_year is not None:
        params["financial_year"] = int(financial_year)
        if int(financial_year) < datetime.now(WIB).year:
            freshness = Freshness.HISTORICAL  # audited past years never change
    return await _call(
        "company_segments", f"/v2/company/get-segments/{sym}/",
        params, freshness, 1, refresh,
    )


@tool
async def sectors_companies_with_segments(refresh: bool = False) -> str:
    """Universe list of tickers that have revenue-segment data, with their
    available financial years — check this before sectors_company_segments.
    1 credit.

    Args:
        refresh: Bypass the cache and fetch fresh data.
    """
    return await _call(
        "companies_with_segments", "/v2/companies/list_companies_with_segments/",
        {}, Freshness.STATIC, 1, refresh,
    )


@tool
async def sectors_index_daily(
    index_code: str,
    start: str | None = None,
    end: str | None = None,
    refresh: bool = False,
) -> str:
    """Daily closing level for one IDX index (ihsg, lq45, idx30, sectoral and
    thematic indices — 17 codes) over a max 90-day window, defaults to the
    last 30 days. The benchmark for relative-performance claims. 1 credit.

    Args:
        index_code: Index slug, e.g. ihsg, lq45, idx30.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        refresh: Bypass the cache and fetch fresh data.
    """
    code = _norm_index(index_code)
    if not code:
        return _err(
            "invalid_index", index_code=index_code,
            hint=f"one of: {', '.join(sorted(_INDEX_CODES))}",
        )
    window = _window(start, end, 90)
    if isinstance(window, str):
        return _err(window)
    return await _call(
        "index_daily", f"/v2/index-daily/{code}/",
        {"start": window[0], "end": window[1]}, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_index_universe(
    date: str | None = None,
    refresh: bool = False,
) -> str:
    """Closing level of every IDX index on one trading day — the whole index
    board in a single call. Defaults to the latest trading day. 1 credit.

    Args:
        date: Trading day YYYY-MM-DD (optional; defaults to latest).
        refresh: Bypass the cache and fetch fresh data.
    """
    day, err = _single_day(date)
    if err:
        return _err(err)
    return await _call(
        "index_universe", "/v2/index-daily/",
        {"date": day} if day else {}, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_market_close(
    date: str | None = None,
    limit: int = 30,
    offset: int = 0,
    refresh: bool = False,
) -> str:
    """Closing price of every IDX ticker on one trading day — the whole tape
    in one paginated feed (~950 rows). Billed PER PAGE, so keep limit high
    and don't page unless the question needs beyond the first page. 1 credit
    per page.

    Args:
        date: Trading day YYYY-MM-DD (optional; defaults to latest).
        limit: Rows per page (max 30).
        offset: Rows to skip for pagination.
        refresh: Bypass the cache and fetch fresh data.
    """
    day, err = _single_day(date)
    if err:
        return _err(err)
    params: dict[str, Any] = {
        "limit": max(1, min(limit, 30)),
        "offset": max(0, offset),
    }
    if day:
        params["date"] = day
    return await _call(
        "market_close", "/v2/close/", params, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_shareholders(
    symbol: str,
    year: int | None = None,
    refresh: bool = False,
) -> str:
    """Monthly shareholder composition for one IDX ticker within a calendar
    year — investor category (insurance, corporate, pension, individual,
    mutual fund, ...) split local vs foreign. Data starts 2021. 1 credit.

    Args:
        symbol: IDX ticker, e.g. BBCA.
        year: Calendar year, 2021 onward. Defaults to the current year.
        refresh: Bypass the cache and fetch fresh data.
    """
    sym = _norm_symbol(symbol)
    if not sym:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
    params: dict[str, Any] = {}
    freshness = Freshness.EOD
    if year is not None:
        current = datetime.now(WIB).year
        if year < _SHAREHOLDERS_FIRST_YEAR or year > current:
            return _err(
                "invalid_year", year=year,
                hint=f"data covers {_SHAREHOLDERS_FIRST_YEAR}–{current}",
            )
        params["year"] = year
        if year < current:
            freshness = Freshness.HISTORICAL
    return await _call(
        "shareholders", f"/v2/company/shareholders-composition/{sym}/",
        params, freshness, 1, refresh,
    )


@tool
async def sectors_company_corporate_actions(
    symbol: str,
    refresh: bool = False,
) -> str:
    """Full corporate-action history for one IDX ticker — splits, right
    issues, warrants, bonus shares, AGMs, and dividends (historical and
    upcoming). The per-symbol counterpart of sectors_corporate_actions.
    1 credit.

    Args:
        symbol: IDX ticker, e.g. BBCA.
        refresh: Bypass the cache and fetch fresh data.
    """
    sym = _norm_symbol(symbol)
    if not sym:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
    return await _call(
        "company_corporate_actions", f"/v2/company/corporate-actions/{sym}/",
        {}, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_quarterly_dates(
    symbol: str,
    refresh: bool = False,
) -> str:
    """Available quarterly report dates for one IDX ticker, grouped by year —
    use these exact dates as `report_date` in sectors_quarterly_financials
    instead of guessing. 1 credit.

    Args:
        symbol: IDX ticker, e.g. BBCA.
        refresh: Bypass the cache and fetch fresh data.
    """
    sym = _norm_symbol(symbol)
    if not sym:
        return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
    return await _call(
        "quarterly_dates", f"/v2/company/get_quarterly_financial_dates/{sym}/",
        {}, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_broker_registry(
    cohort: str | None = None,
    origin: str | None = None,
    refresh: bool = False,
) -> str:
    """Registry of IDX exchange-member brokers — code → name, origin
    (foreign/domestic), cohort (retail/mixed/institutional/unknown), license
    type. The authoritative decode for broker codes other tools return.
    1 credit.

    Args:
        cohort: Optional filter — institutional, mixed, retail, unknown.
        origin: Optional filter — domestic or foreign.
        refresh: Bypass the cache and fetch fresh data.
    """
    params: dict[str, Any] = {}
    if cohort:
        c = cohort.strip().lower()
        if c not in _BROKER_COHORTS - {"all"}:
            return _err(
                "invalid_cohort", cohort=cohort,
                allowed=sorted(_BROKER_COHORTS - {"all"}),
            )
        params["cohort"] = c
    if origin:
        o = origin.strip().lower()
        if o not in _BROKER_ORIGINS:
            return _err("invalid_origin", origin=origin, allowed=sorted(_BROKER_ORIGINS))
        params["origin"] = o
    return await _call(
        "broker_registry", "/v2/brokers/", params, Freshness.STATIC, 1, refresh,
    )


@tool
async def sectors_broker_activity(
    broker_code: str,
    symbol: str | None = None,
    start: str | None = None,
    end: str | None = None,
    refresh: bool = False,
) -> str:
    """Every stock one broker traded per day, grouped by date, with
    buy/sell/net values and the foreign-investor split (max 14-day window,
    defaults to last 14 days). 1 credit. Valid codes via
    sectors_broker_registry.

    Args:
        broker_code: Two-letter exchange member code, e.g. MG, AK.
        symbol: Optional IDX ticker to narrow to one stock.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        refresh: Bypass the cache and fetch fresh data.
    """
    code = _norm_broker(broker_code)
    if not code:
        return _err("invalid_broker_code", broker_code=broker_code, hint="2 letters, e.g. MG")
    window = _window(start, end, 14)
    if isinstance(window, str):
        return _err(window)
    params: dict[str, Any] = {"start": window[0], "end": window[1]}
    if symbol:
        sym = _norm_symbol(symbol)
        if not sym:
            return _err("invalid_symbol", symbol=symbol, hint="IDX tickers are 4 letters, e.g. BBCA")
        params["symbol"] = sym
    return await _call(
        "broker_activity", f"/v2/broker-activity/{code}/",
        params, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_broker_activity_top(
    broker_code: str,
    start: str | None = None,
    end: str | None = None,
    foreign: bool = False,
    refresh: bool = False,
) -> str:
    """Stocks one broker has been most actively accumulating and distributing
    (net IDR) over a max 90-day window, defaults to last 90 days. 2 credits.

    Args:
        broker_code: Two-letter exchange member code, e.g. MG.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        foreign: Rank by the foreign-investor portion of the broker's flow.
        refresh: Bypass the cache and fetch fresh data.
    """
    code = _norm_broker(broker_code)
    if not code:
        return _err("invalid_broker_code", broker_code=broker_code, hint="2 letters, e.g. MG")
    window = _window(start, end, 90)
    if isinstance(window, str):
        return _err(window)
    return await _call(
        "broker_activity_top", f"/v2/broker-activity/{code}/top/",
        {"start": window[0], "end": window[1], "foreign": foreign},
        Freshness.EOD, 2, refresh,
    )


@tool
async def sectors_top_brokers(
    date: str | None = None,
    metric: str = "gross",
    cohort: str = "all",
    origin: str | None = None,
    foreign: bool = False,
    n_brokers: int | None = None,
    refresh: bool = False,
) -> str:
    """Brokers ranked for one trading day by gross trade value or absolute
    net flow — who moved the market that day. 2 credits.

    Args:
        date: Trading day YYYY-MM-DD (optional; defaults to latest).
        metric: gross (turnover) or net (absolute net flow).
        cohort: all, institutional, mixed, retail, or unknown.
        origin: Optional — domestic or foreign brokers only.
        foreign: Rank by the foreign-investor portion of each broker's flow.
        n_brokers: Optional cap; omit for all matching brokers.
        refresh: Bypass the cache and fetch fresh data.
    """
    day, err = _single_day(date)
    if err:
        return _err(err)
    m = metric.strip().lower()
    if m not in _TOP_BROKER_METRICS:
        return _err("invalid_metric", metric=metric, allowed=sorted(_TOP_BROKER_METRICS))
    c = cohort.strip().lower()
    if c not in _BROKER_COHORTS:
        return _err("invalid_cohort", cohort=cohort, allowed=sorted(_BROKER_COHORTS))
    params: dict[str, Any] = {"metric": m, "cohort": c, "foreign": foreign}
    if day:
        params["date"] = day
    if origin:
        o = origin.strip().lower()
        if o not in _BROKER_ORIGINS:
            return _err("invalid_origin", origin=origin, allowed=sorted(_BROKER_ORIGINS))
        params["origin"] = o
    if n_brokers is not None:
        params["n_brokers"] = max(1, n_brokers)
    return await _call(
        "top_brokers", "/v2/brokers/top/", params, Freshness.EOD, 2, refresh,
    )


@tool
async def sectors_foreign_flow_universe(
    date: str | None = None,
    order_by: str = "-net_foreign_inflow",
    limit: int = 20,
    offset: int = 0,
    refresh: bool = False,
) -> str:
    """Net foreign-investor flow of every IDX ticker on one trading day —
    the market-wide counterpart of sectors_foreign_flow. Sorted by net
    inflow descending by default (top foreign buys); flip sign of order_by
    for top sells. Billed PER PAGE — the full universe is ~20+ pages, so
    don't page beyond what the question needs. 1 credit per page.

    Args:
        date: Trading day YYYY-MM-DD (optional; defaults to latest).
        order_by: net_foreign_inflow, foreign_buy_idr, foreign_sell_idr, or
            symbol — prefix with - for descending.
        limit: Tickers per page (max 30).
        offset: Tickers to skip for pagination.
        refresh: Bypass the cache and fetch fresh data.
    """
    day, err = _single_day(date)
    if err:
        return _err(err)
    ob = order_by.strip()
    if ob not in _FLOW_ORDER:
        return _err("invalid_order_by", order_by=order_by, allowed=sorted(_FLOW_ORDER))
    params: dict[str, Any] = {
        "order_by": ob,
        "limit": max(1, min(limit, 30)),
        "offset": max(0, offset),
    }
    if day:
        params["date"] = day
    return await _call(
        "foreign_flow_universe", "/v2/foreign-flow/",
        params, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_free_float(
    sector: str | None = None,
    sub_sector: str | None = None,
    industry: str | None = None,
    sub_industry: str | None = None,
    refresh: bool = False,
) -> str:
    """Free float % (public share) of IDX companies, ordered highest first —
    one taxonomy filter per call, or none for the whole market. Billed ~1
    credit per 100 companies returned, so filter to keep it cheap.

    Args:
        sector: Kebab-case sector slug (mutually exclusive with the others).
        sub_sector: Kebab-case subsector slug.
        industry: Kebab-case industry slug.
        sub_industry: Kebab-case sub-industry slug.
        refresh: Bypass the cache and fetch fresh data.
    """
    filters = {
        "sector": sector, "sub_sector": sub_sector,
        "industry": industry, "sub_industry": sub_industry,
    }
    given = {k: v for k, v in filters.items() if v}
    if len(given) > 1:
        return _err(
            "conflicting_filters",
            hint="pass at most one of sector/sub_sector/industry/sub_industry",
        )
    params: dict[str, Any] = {}
    if given:
        key, raw = next(iter(given.items()))
        slug = _norm_slug(raw)
        if not slug:
            return _err(f"invalid_{key}", hint="kebab-case slug, e.g. banks")
        params[key] = slug
    return await _call(
        "free_float", "/v2/free-float/", params, Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_list_industries(refresh: bool = False) -> str:
    """All IDX subsector/industry slug pairs — valid inputs for `industry`
    filters. Reference data, cached for days. 1 credit.

    Args:
        refresh: Bypass the cache and fetch fresh data.
    """
    return await _call("industries", "/v2/industries/", {}, Freshness.STATIC, 1, refresh)


@tool
async def sectors_list_subindustries(refresh: bool = False) -> str:
    """All IDX industry/sub-industry slug pairs — valid inputs for
    `sub_industry` filters. Reference data, cached for days. 1 credit.

    Args:
        refresh: Bypass the cache and fetch fresh data.
    """
    return await _call(
        "subindustries", "/v2/subindustries/", {}, Freshness.STATIC, 1, refresh,
    )


@tool
async def sectors_list_tags(refresh: bool = False) -> str:
    """All tag slugs used across IDX news and filings — valid inputs for
    `tags` filters. Reference data, cached for days. 1 credit.

    Args:
        refresh: Bypass the cache and fetch fresh data.
    """
    return await _call("tags", "/v2/tags/", {}, Freshness.STATIC, 1, refresh)


@tool
async def sectors_compare(
    symbols: str,
    sections: list[str] = ["overview", "valuation"],
    refresh: bool = False,
) -> str:
    """Side-by-side pull for several IDX tickers — fans out to the per-company
    report in parallel and returns a {symbol: envelope} map in one call.
    Billed per section per symbol (defaults: overview + valuation), so keep
    both lists tight. For anything deeper per company call
    sectors_company_report directly.

    Args:
        symbols: Comma-separated IDX tickers, e.g. "BBCA,BBRI,BMRI" (max 8).
        sections: company_report sections to compare — overview, valuation,
            financials, peers, dividend, future, management, ownership.
        refresh: Bypass the cache and fetch fresh data.
    """
    syms = _norm_symbols(symbols)
    if not syms:
        return _err(
            "invalid_symbols", symbols=symbols,
            hint="comma-separated 4-letter IDX tickers, e.g. 'BBCA,BBRI'",
        )
    chosen = _pick(sections, _COMPANY_SECTIONS, ["overview", "valuation"])
    return await _fanout(
        "company_report", "/v2/company/report/{}/",
        {"sections": ",".join(chosen)},
        Freshness.EOD, len(chosen), refresh, syms,
    )


# ---------------------------------------------------------------------------
# Mining extension — Indonesian miners, commodity prices, production, trade.
# Annual/slow-moving data → STATIC cache; monthly prices → EOD.
# ---------------------------------------------------------------------------

# Valid `commodity_type` values differ per endpoint — keep them separate so a
# wrong value fails locally with a hint instead of burning the request.
_MINING_COMPANY_COMMODITIES = {
    "aluminium": "Aluminium", "coal": "Coal", "copper": "Copper",
    "gold": "Gold", "nickel": "Nickel", "silver": "Silver",
    "zinc and lead": "Zinc and Lead",
}
_MINING_COMPANY_TYPES = {
    "consultant": "Consultant", "contractor": "Contractor",
    "holding": "Holding", "manufacturer": "Manufacturer",
    "mine owner": "Mine Owner", "trader": "Trader",
}
_MINING_PERF_COMMODITIES = {
    "coal": "Coal", "copper": "Copper", "gold": "Gold", "nickel": "Nickel",
    "silver": "Silver",
}
_MINING_SITE_COMMODITIES = {
    "coal": "Coal", "copper": "Copper", "gold": "Gold", "nickel": "Nickel",
}
_MINING_EXPORT_COMMODITIES = {
    "coal": "Coal", "copper": "Copper", "gold": "Gold",
}
_MINING_GLOBAL_COMMODITIES = {
    "bauxite": "Bauxite", "coal": "Coal", "copper": "Copper", "gold": "Gold",
    "nickel": "Nickel",
}
_MINING_SITE_SORTS = {
    "production_volume", "-production_volume",
    "strip_ratio", "-strip_ratio", "year", "-year",
}


def _norm_mining_value(value: str, allowed: dict[str, str], field: str):
    """Case-insensitive enum normalize → canonical casing or error."""
    v = allowed.get(value.strip().lower())
    if v is None:
        return None, _err(
            f"invalid_{field}",
            hint=f"one of: {', '.join(allowed.values())}",
        )
    return v, None


@tool
async def sectors_mining_companies(
    keyword: str | None = None,
    commodity_type: str | None = None,
    company_type: str | None = None,
    has_financials: bool | None = None,
    limit: int = 20,
    refresh: bool = False,
) -> str:
    """Search Indonesian mining companies by name, IDX ticker, or key
    operation — filterable by commodity and company type. Results carry the
    `slug` needed by the detail/performance/site tools; `symbol` is null for
    private subsidiaries of listed groups. 1 credit.

    Args:
        keyword: Search text — company name, IDX symbol (e.g. "ADRO"), slug,
            or operation (e.g. "coal mining").
        commodity_type: Aluminium, Coal, Copper, Gold, Nickel, Silver, or
            "Zinc and Lead".
        company_type: Consultant, Contractor, Holding, Manufacturer,
            Mine Owner, or Trader.
        has_financials: True to keep only companies with financial data.
        limit: Results per page, max 30.
        refresh: Bypass the cache and fetch fresh data.
    """
    params: dict[str, Any] = {}
    if keyword:
        params["keyword"] = keyword.strip()
    if commodity_type:
        v, err = _norm_mining_value(
            commodity_type, _MINING_COMPANY_COMMODITIES, "commodity_type"
        )
        if err:
            return err
        params["commodity_type"] = v
    if company_type:
        v, err = _norm_mining_value(
            company_type, _MINING_COMPANY_TYPES, "company_type"
        )
        if err:
            return err
        params["company_type"] = v
    if has_financials is not None:
        params["has_financials"] = has_financials
    params["limit"] = min(max(limit, 1), 30)
    return await _call(
        "mining_companies", "/v2/mining/companies/", params,
        Freshness.STATIC, 1, refresh,
    )


@tool
async def sectors_mining_company_detail(slug: str, refresh: bool = False) -> str:
    """Operational detail for one mining company — activities, commodities,
    IUPK licenses, contracts, site count, contacts. Get slugs from
    sectors_mining_companies. 1 credit.

    Args:
        slug: Kebab-case company slug, e.g. "pt-adaro-indonesia".
        refresh: Bypass the cache and fetch fresh data.
    """
    s = _norm_slug(slug)
    if not s:
        return _err(
            "invalid_slug",
            hint="kebab-case slug from sectors_mining_companies, e.g. 'pt-adaro-indonesia'",
        )
    return await _call(
        "mining_company_detail", f"/v2/mining/companies/{s}/", {},
        Freshness.STATIC, 1, refresh,
    )


@tool
async def sectors_mining_company_performance(
    slug: str,
    year: int | None = None,
    commodity_type: str | None = None,
    refresh: bool = False,
) -> str:
    """Annual operating performance for a mining company — production and
    sales volumes, strip ratio, resources/reserves, product specs. Pair with
    sectors_quarterly_financials to tie physical output to financial results.
    1 credit.

    Args:
        slug: Kebab-case company slug from sectors_mining_companies.
        year: Reporting year (e.g. 2024); defaults to the latest available.
        commodity_type: Coal, Copper, Gold, Nickel, or Silver.
        refresh: Bypass the cache and fetch fresh data.
    """
    s = _norm_slug(slug)
    if not s:
        return _err(
            "invalid_slug",
            hint="kebab-case slug from sectors_mining_companies, e.g. 'pt-adaro-indonesia'",
        )
    params: dict[str, Any] = {}
    if year is not None:
        params["year"] = year
    if commodity_type:
        v, err = _norm_mining_value(
            commodity_type, _MINING_PERF_COMMODITIES, "commodity_type"
        )
        if err:
            return err
        params["commodity_type"] = v
    return await _call(
        "mining_company_performance", f"/v2/mining/companies/performance/{s}/",
        params, Freshness.STATIC, 1, refresh,
    )


@tool
async def sectors_commodity_prices(
    commodity: str,
    start_year: int | None = None,
    end_year: int | None = None,
    refresh: bool = False,
) -> str:
    """Monthly price history for a commodity (USD/ton) — Coal, Gold, Nickel,
    Copper, and more. The demand driver behind every IDX miner; max 3-year
    range per call (longer windows get clamped to the latest 3 years).
    1 credit.

    Args:
        commodity: Commodity name, e.g. "Coal", "Nickel", "Gold".
        start_year: First year (defaults to end_year − 2).
        end_year: Last year, inclusive (defaults to the current year).
        refresh: Bypass the cache and fetch fresh data.
    """
    name = commodity.strip().title()
    if not name:
        return _err("invalid_commodity", hint="e.g. Coal, Nickel, Gold")
    this_year = datetime.now(timezone.utc).year
    end = min(end_year or this_year, this_year)
    start = start_year or end - 2
    if start > end:
        return _err("invalid_year", hint="start_year must not exceed end_year")
    if end - start >= 3:
        start = end - 2  # upstream caps at a 3-year window
    return await _call(
        "commodity_price", f"/v2/mining/commodities/{name}/price/",
        {"start_year": start, "end_year": end},
        Freshness.EOD, 1, refresh,
    )


@tool
async def sectors_mining_sites(
    province: str | None = None,
    commodity_type: str | None = None,
    company: str | None = None,
    year: int | None = None,
    order_by: str = "-year",
    min_production: float | None = None,
    limit: int = 20,
    refresh: bool = False,
) -> str:
    """Mining sites across Indonesia — filter by province, commodity, company
    slug, or reporting year; sortable. Rows carry per-site production volume,
    strip ratio, and coordinates. 1 credit.

    Args:
        province: Exact province name, e.g. "Kalimantan Timur".
        commodity_type: Coal, Copper, Gold, or Nickel.
        company: Company slug from sectors_mining_companies.
        year: Reporting year.
        order_by: production_volume, strip_ratio, or year — prefix "-"
            for descending (default "-year").
        min_production: Keep sites at or above this production volume.
        limit: Results per page, max 30.
        refresh: Bypass the cache and fetch fresh data.
    """
    params: dict[str, Any] = {}
    if province:
        params["province"] = province.strip().title()
    if commodity_type:
        v, err = _norm_mining_value(
            commodity_type, _MINING_SITE_COMMODITIES, "commodity_type"
        )
        if err:
            return err
        params["commodity_type"] = v
    if company:
        s = _norm_slug(company)
        if not s:
            return _err("invalid_company", hint="company slug, e.g. 'pt-maruwai-coal'")
        params["company"] = s
    if year is not None:
        params["year"] = year
    if order_by not in _MINING_SITE_SORTS:
        return _err(
            "invalid_order_by",
            hint="production_volume | strip_ratio | year (prefix '-' for desc)",
        )
    params["order_by"] = order_by
    if min_production is not None:
        params["min_production"] = min_production
    params["limit"] = min(max(limit, 1), 30)
    return await _call(
        "mining_sites", "/v2/mining/sites/", params,
        Freshness.STATIC, 1, refresh,
    )


@tool
async def sectors_mining_exports(
    commodity_type: str,
    year: int,
    limit: int = 10,
    refresh: bool = False,
) -> str:
    """Top export destinations for an Indonesian commodity in a year —
    export value USD plus BPS/ESDM volumes. The demand-side context behind
    a miner's revenue. 1 credit.

    Args:
        commodity_type: Coal, Copper, or Gold.
        year: The year to analyze (e.g. 2024).
        limit: Top countries to return, max 30.
        refresh: Bypass the cache and fetch fresh data.
    """
    v, err = _norm_mining_value(
        commodity_type, _MINING_EXPORT_COMMODITIES, "commodity_type"
    )
    if err:
        return err
    return await _call(
        "mining_exports", "/v2/mining/exports/",
        {"commodity_type": v, "year": year, "limit": min(max(limit, 1), 30)},
        Freshness.STATIC, 1, refresh,
    )


@tool
async def sectors_global_commodity(
    commodity_type: str | None = None,
    country: str | None = None,
    limit: int = 20,
    refresh: bool = False,
) -> str:
    """Global production, reserves, and trade data — for one commodity across
    countries, or one country's commodity footprint. At least one of the two
    arguments is required. 1 credit.

    Args:
        commodity_type: Coal, Gold, Nickel, Copper, or Bauxite.
        country: Exact country name, e.g. "Australia".
        limit: Results to return, max 30.
        refresh: Bypass the cache and fetch fresh data.
    """
    params: dict[str, Any] = {"limit": min(max(limit, 1), 30)}
    if commodity_type:
        v, err = _norm_mining_value(
            commodity_type, _MINING_GLOBAL_COMMODITIES, "commodity_type"
        )
        if err:
            return err
        params["commodity_type"] = v
    if country:
        params["country"] = country.strip().title()
    if "commodity_type" not in params and "country" not in params:
        return _err(
            "missing_filter",
            hint="pass commodity_type (Coal/Gold/Nickel/Copper/Bauxite) or a country name",
        )
    return await _call(
        "global_commodity", "/v2/mining/global-commodity/", params,
        Freshness.STATIC, 1, refresh,
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
    sectors_company_segments,
    sectors_companies_with_segments,
    sectors_index_daily,
    sectors_index_universe,
    sectors_market_close,
    sectors_shareholders,
    sectors_company_corporate_actions,
    sectors_quarterly_dates,
    sectors_broker_registry,
    sectors_broker_activity,
    sectors_broker_activity_top,
    sectors_top_brokers,
    sectors_foreign_flow_universe,
    sectors_free_float,
    sectors_list_industries,
    sectors_list_subindustries,
    sectors_list_tags,
    sectors_compare,
    sectors_mining_companies,
    sectors_mining_company_detail,
    sectors_mining_company_performance,
    sectors_commodity_prices,
    sectors_mining_sites,
    sectors_mining_exports,
    sectors_global_commodity,
]
