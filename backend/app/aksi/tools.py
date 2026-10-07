"""Aksi tools for the chat agent — holdings CRUD, run/read checks, impact.

Deterministic: same calendar + calculators as the Aksi page, no LLM inside.
Tools that act on the user's account read `user_id` from the turn's config.
"""

import asyncio
import json
import re
from datetime import date

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agent.runs import RunLimitError, registry
from app.aksi import budget as budget_mod
from app.aksi import events, impact, service, store

_SYMBOL = re.compile(r"^[A-Z]{4}$")
_MIN_DATE = date(2021, 1, 1)


def _as_of(raw: str | None) -> date | None | str:
    """Parse a replay date — returns the date, None, or an error string."""
    try:
        day = date.fromisoformat(raw) if raw else None
    except ValueError:
        return "invalid_date"
    if day is not None and not (_MIN_DATE <= day <= events.today_wib()):
        return "invalid_date"
    return day


def _uid(config: RunnableConfig) -> int | None:
    uid = (config.get("configurable") or {}).get("user_id")
    try:
        return int(uid) if uid is not None else None
    except (TypeError, ValueError):
        return None


def _symbol(raw: str) -> str:
    return raw.strip().upper().removesuffix(".JK")


def _summary(report: dict) -> dict:
    """Report → compact per-event digest for the LLM's context."""
    events = []
    for e in report["events"]:
        ev = e["event"]
        brief = e.get("brief") or {}
        events.append({
            "symbol": ev["symbol"],
            "kind": ev["kind"],
            "phase": ev["phase"],
            "urgency_days": ev.get("urgency"),
            "figures": {k: v.get("value") for k, v in (e.get("figures") or {}).items()
                        if v.get("value") is not None},
            "headline_en": brief.get("headline_en"),
            "headline_id": brief.get("headline_id"),
        })
    return {"report_id": report["id"], "mode": report["mode"], "as_of": report["as_of"],
            "status": report["status"], "events": events,
            "credits_spent": report["credits_spent"], "page": "/action"}


@tool
async def aksi_impact(symbol: str, shares: int, as_of: str | None = None) -> str:
    """Corporate actions (rights issue/HMETD, dividends, warrants) affecting a
    holding, with the holder's personal figures computed in code: rights
    entitled, cost to exercise, theoretical ex-rights price, dilution if
    ignored, gross dividend, deadlines. Use for any holder-specific number —
    never compute these mentally. Never advise buying, selling or exercising.

    Args:
        symbol: IDX ticker, e.g. WIFI.
        shares: Number of shares held (lembar; 1 lot = 100 shares).
        as_of: Optional YYYY-MM-DD for a historical replay (default: today).
    """
    sym = _symbol(symbol)
    if (
        not _SYMBOL.match(sym)
        or int(shares) != shares
        or not 1 <= int(shares) <= 10**12
    ):
        return json.dumps({"error": "invalid_input"})
    day = _as_of(as_of)
    if isinstance(day, str):
        return json.dumps({"error": day})
    return json.dumps(await impact.impact(sym, int(shares), day), default=str)


@tool
async def holdings_list(config: RunnableConfig) -> str:
    """List the user's saved stock holdings (ticker, shares, average buy price)
    — the portfolio tracked for corporate actions."""
    uid = _uid(config)
    if uid is None:
        return json.dumps({"error": "no_user"})
    return json.dumps({"holdings": await store.list_holdings(uid)})


@tool
async def holdings_save(symbol: str, shares: int, config: RunnableConfig,
                        avg_price: float | None = None) -> str:
    """Add a stock holding to the user's tracked portfolio, or update it if the
    ticker is already tracked. Use when the user says they own shares or wants
    a ticker followed.

    Args:
        symbol: IDX ticker, e.g. BBCA.
        shares: Number of shares held (lembar; 1 lot = 100 shares).
        avg_price: Optional average buy price per share in IDR.
    """
    uid = _uid(config)
    sym = _symbol(symbol)
    if uid is None:
        return json.dumps({"error": "no_user"})
    if (
        not _SYMBOL.match(sym)
        or int(shares) != shares
        or not 1 <= int(shares) <= 10**12
        or (avg_price is not None and not 0 < avg_price <= 10**12)
    ):
        return json.dumps({"error": "invalid_input",
                           "detail": "symbol must be a 4-letter IDX ticker; "
                                     "shares a whole number 1..1e12; "
                                     "avg_price a positive number <= 1e12"})
    holdings = [h for h in await store.list_holdings(uid) if h["symbol"] != sym]
    holdings.append({"symbol": sym, "shares": int(shares), "avg_price": avg_price})
    await store.replace_holdings(uid, holdings)
    return json.dumps({"holdings": await store.list_holdings(uid)})


@tool
async def holdings_remove(symbol: str, config: RunnableConfig) -> str:
    """Remove a ticker from the user's tracked holdings.

    Args:
        symbol: IDX ticker, e.g. BBCA.
    """
    uid = _uid(config)
    sym = _symbol(symbol)
    if uid is None:
        return json.dumps({"error": "no_user"})
    holdings = await store.list_holdings(uid)
    kept = [h for h in holdings if h["symbol"] != sym]
    if len(kept) == len(holdings):
        return json.dumps({"error": "not_found", "holdings": holdings})
    await store.replace_holdings(uid, kept)
    return json.dumps({"holdings": kept})


@tool
async def aksi_reports(config: RunnableConfig, limit: int = 10) -> str:
    """List the user's past corporate-actions checks, newest first — report id,
    mode (live/replay), the date each was run as-of, status, event count and
    credits spent. Use to find which checks exist before opening one with
    aksi_report.

    Args:
        limit: Max reports to return (default 10).
    """
    uid = _uid(config)
    if uid is None:
        return json.dumps({"error": "no_user"})
    rows = await store.list_reports(uid, max(1, min(50, int(limit))))
    return json.dumps({"reports": [{
        "report_id": r["id"], "mode": r["mode"], "as_of": r["as_of"],
        "status": r["status"], "events": r["events"],
        "credits_spent": r["credits_spent"], "created_at": r["created_at"],
    } for r in rows]}, default=str)


@tool
async def aksi_report(config: RunnableConfig, report_id: str | None = None,
                      mode: str | None = None,
                      as_of: str | None = None) -> str:
    """Read a saved corporate-actions check report: per event, the ticker,
    action kind, phase, deadline, their personal figures and the brief
    headline. Use to answer "what did the last check find" or to review a past
    live/replay check without running a new one.

    Args:
        report_id: Optional id from aksi_reports — opens that exact report.
        mode: Optional "live" or "replay" filter when no id is given.
        as_of: Optional YYYY-MM-DD — only a report for that date.
    """
    uid = _uid(config)
    if uid is None:
        return json.dumps({"error": "no_user"})
    if report_id:
        report = await store.get_report(uid, report_id)
    else:
        if mode not in (None, "live", "replay"):
            return json.dumps({"error": "invalid_mode"})
        day = _as_of(as_of)
        if isinstance(day, str):
            return json.dumps({"error": day})
        report = await store.latest_report(uid, mode, day)
    if report is None:
        return json.dumps({"error": "no_report"})
    return json.dumps(_summary(report), default=str)


@tool
async def aksi_check(config: RunnableConfig, as_of: str | None = None,
                     symbols: list[str] | None = None,
                     budget: int | None = None) -> str:
    """Run a full corporate-actions check across the user's saved holdings:
    scans the market calendar, keeps the actions touching their tickers,
    computes their personal figures in code, and saves the report — the same
    pipeline as the Corporate Actions page, so it appears there too. Takes
    about a minute and spends Sectors credits — call only when the user asks
    for a check.

    Args:
        as_of: Optional YYYY-MM-DD for a historical replay (default: today).
        symbols: Optional subset of tracked tickers to check (all if omitted).
        budget: Optional Sectors credit cap for the run (5-40, default 25).
    """
    uid = _uid(config)
    if uid is None:
        return json.dumps({"error": "no_user"})
    if not await store.list_holdings(uid):
        return json.dumps({"error": "no_holdings",
                           "detail": "No saved holdings — save tickers with "
                                     "holdings_save first."})
    day = _as_of(as_of)
    if isinstance(day, str):
        return json.dumps({"error": day})
    tickers = [_symbol(s) for s in (symbols or [])]
    bad = [s for s in tickers if not _SYMBOL.match(s)]
    if bad:
        return json.dumps({"error": "invalid_symbols", "symbols": bad})
    cap = budget_mod.DEFAULT_BUDGET if budget is None else max(5, min(40, int(budget)))
    key = service.run_key(uid)
    async with registry.thread_lock(key):
        await registry.stop_and_wait(key)  # a new check supersedes a live one
        try:
            run = registry.start_run(uid, key)
        except RunLimitError as exc:
            return json.dumps({"error": "limit", "detail": str(exc)})
        run.task = asyncio.create_task(
            service.run_check(run, uid, day, tickers or None, cap))
    # Shielded: the detached run must finish and persist even if this chat
    # turn is cancelled mid-wait.
    await asyncio.shield(run.task)
    report = await store.latest_report(uid)
    if report is None:
        return json.dumps({"error": "no_report"})
    return json.dumps(_summary(report), default=str)
