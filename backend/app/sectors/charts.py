"""Chart detection: JEV judges chartability + picks a view; code builds the spec.

Per tool result with registered views, one jev_ask asks in parallel whether a
chart adds clarity (Noul) and which view fits best (Choice over the tool's
registered views + "none"). Extractors are deterministic data-shapers keyed by
view — the model never writes the spec. Any failure → no chart; the turn is
never affected.
"""

import json
import logging
import uuid
from typing import Any, Callable

from app.core.jev import Choice, Noul, jev_ask

logger = logging.getLogger(__name__)

# (data, fetched_at) -> spec dict | None
Extractor = Callable[[Any, str], "dict[str, Any] | None"]


def _rows(data: Any) -> list[dict]:
    """Coerce the common `data` shapes into a dict-row list."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [r for r in data["data"] if isinstance(r, dict)]
    return []


def _sym(value: Any) -> str:
    """Strip the IDX suffix for display — 'BBCA.JK' → 'BBCA'."""
    return str(value or "").removesuffix(".JK")


def _spec(
    view: str,
    kind: str,
    title: str,
    x: dict[str, str],
    series: list[dict[str, str]],
    data: list[dict],
    fetched_at: str,
    fmt: str,
) -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "view": view,
        "kind": kind,
        "title": title,
        "x": x,
        "series": series,
        "data": data,
        "fetched_at": fetched_at,
        "format": fmt,
    }


# -- extractors ---------------------------------------------------------------


def _price_volume(data: Any, fetched_at: str) -> dict | None:
    rows = _rows(data)
    pts = [
        {"date": r["date"], "close": r["close"], "volume": r.get("volume")}
        for r in rows
        if r.get("date") and r.get("close") is not None
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r["date"])
    sym = _sym(rows[0].get("symbol"))
    return _spec(
        "price_volume",
        "price_volume",
        f"{sym} daily close",
        {"key": "date", "label": "Date", "type": "time"},
        [
            {"key": "close", "label": "Close"},
            {"key": "volume", "label": "Volume"},
        ],
        pts,
        fetched_at,
        "number",
    )


def _mcap_area(data: Any, fetched_at: str) -> dict | None:
    pts = [
        {"date": r["date"], "mcap": r["idx_total_market_cap"]}
        for r in _rows(data)
        if r.get("date") and r.get("idx_total_market_cap") is not None
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r["date"])
    return _spec(
        "mcap_area", "area", "IDX total market cap",
        {"key": "date", "label": "Date", "type": "time"},
        [{"key": "mcap", "label": "Total market cap"}],
        pts, fetched_at, "idr",
    )


def _netflow(data: Any, fetched_at: str) -> dict | None:
    pts = [
        {"date": r["date"], "net": r["net_foreign_inflow"]}
        for r in _rows(data)
        if r.get("date") and r.get("net_foreign_inflow") is not None
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r["date"])
    sym = _sym(data.get("symbol")) if isinstance(data, dict) else ""
    return _spec(
        "netflow", "signed_area", f"{sym} net foreign flow",
        {"key": "date", "label": "Date", "type": "time"},
        [{"key": "net", "label": "Net foreign inflow"}],
        pts, fetched_at, "idr",
    )


def _quarterly_grouped(data: Any, fetched_at: str) -> dict | None:
    rows = _rows(data)
    pts = [
        {"date": r["date"], "revenue": r.get("revenue"),
         "earnings": r.get("earnings")}
        for r in rows
        if r.get("date")
        and (r.get("revenue") is not None or r.get("earnings") is not None)
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r["date"])
    sym = _sym(rows[0].get("symbol"))
    return _spec(
        "quarterly_grouped", "grouped_bar",
        f"{sym} quarterly revenue vs earnings",
        {"key": "date", "label": "Quarter", "type": "category"},
        [{"key": "revenue", "label": "Revenue"},
         {"key": "earnings", "label": "Earnings"}],
        pts, fetched_at, "idr",
    )


def _perf_bars(data: Any, fetched_at: str) -> dict | None:
    if not isinstance(data, dict):
        return None
    pts = [
        {"window": w, "change": data[k]}
        for w, k in [
            ("7d", "chg_7d"), ("30d", "chg_30d"),
            ("90d", "chg_90d"), ("365d", "chg_365d"),
        ]
        if data.get(k) is not None
    ]
    if len(pts) < 2:
        return None
    sym = _sym(data.get("symbol"))
    return _spec(
        "perf_bars", "bar", f"{sym} performance since listing",
        {"key": "window", "label": "Window", "type": "category"},
        [{"key": "change", "label": "% change"}],
        pts, fetched_at, "percent_raw",
    )


_MOVER_LABELS = {"top_gainers": "Top gainers", "top_losers": "Top losers"}


def _movers(data: Any, fetched_at: str) -> dict | None:
    if not isinstance(data, dict):
        return None
    pts = []
    for cls, periods in data.items():
        if not isinstance(periods, dict):
            continue
        for period, rows in periods.items():
            for r in rows or []:
                if isinstance(r, dict) and r.get("symbol") and r.get("price_change") is not None:
                    pts.append({
                        "group": f"{_MOVER_LABELS.get(cls, cls)} {period}",
                        "symbol": _sym(r["symbol"]),
                        "name": r.get("name", ""),
                        "change": r["price_change"],
                    })
    if len(pts) < 2:
        return None
    return _spec(
        "movers", "diverging_bar", "Top movers",
        {"key": "symbol", "label": "Symbol", "type": "category"},
        [{"key": "change", "label": "Price change"}],
        pts, fetched_at, "percent",
    )


def _traded_bars(data: Any, fetched_at: str) -> dict | None:
    if not isinstance(data, dict):
        return None
    days = [d for d, v in data.items() if isinstance(v, list)]
    if not days:
        return None
    day = max(days)
    pts = [
        {"symbol": _sym(r["symbol"]), "volume": r["volume"]}
        for r in data[day]
        if isinstance(r, dict) and r.get("symbol") and r.get("volume") is not None
    ]
    if len(pts) < 2:
        return None
    return _spec(
        "traded_bars", "bar", f"Most traded {day}",
        {"key": "symbol", "label": "Symbol", "type": "category"},
        [{"key": "volume", "label": "Volume"}],
        pts, fetched_at, "number",
    )


def _traded_trend(data: Any, fetched_at: str) -> dict | None:
    if not isinstance(data, dict):
        return None
    days = sorted(d for d, v in data.items() if isinstance(v, list))
    if len(days) < 3:
        return None
    totals: dict[str, float] = {}
    for d in days:
        for r in data[d]:
            if isinstance(r, dict) and r.get("symbol") and r.get("volume") is not None:
                totals[r["symbol"]] = totals.get(r["symbol"], 0) + r["volume"]
    top = sorted(totals, key=lambda s: totals[s], reverse=True)[:5]
    if len(top) < 2:
        return None
    pts = []
    for d in days:
        row: dict[str, Any] = {"date": d}
        vols = {
            r.get("symbol"): r.get("volume")
            for r in data[d] if isinstance(r, dict)
        }
        for s in top:
            row[_sym(s)] = vols.get(s)
        pts.append(row)
    return _spec(
        "traded_trend", "line", "Most-traded volume by day",
        {"key": "date", "label": "Date", "type": "time"},
        [{"key": _sym(s), "label": _sym(s)} for s in top],
        pts, fetched_at, "number",
    )


def _broker_net_bars(data: Any, fetched_at: str) -> dict | None:
    if not isinstance(data, dict):
        return None
    nets: dict[str, float] = {}
    for entry in data.get("data") or []:
        for r in (entry or {}).get("summary") or []:
            if isinstance(r, dict) and r.get("broker_code") and r.get("nval") is not None:
                nets[r["broker_code"]] = nets.get(r["broker_code"], 0) + r["nval"]
    top = sorted(nets.items(), key=lambda kv: abs(kv[1]), reverse=True)[:10]
    if len(top) < 2:
        return None
    sym = _sym(data.get("symbol"))
    return _spec(
        "broker_net_bars", "diverging_bar", f"{sym} net broker flow",
        {"key": "symbol", "label": "Broker", "type": "category"},
        [{"key": "net", "label": "Net IDR"}],
        [{"symbol": b, "net": v} for b, v in top],
        fetched_at, "idr",
    )


def _broker_rank_bars(data: Any, fetched_at: str) -> dict | None:
    if not isinstance(data, dict):
        return None
    pts = []
    for group, rows in [("Top buyers", data.get("top_buyers")),
                        ("Top sellers", data.get("top_sellers"))]:
        for r in rows or []:
            if isinstance(r, dict) and r.get("broker_code") and r.get("net_idr") is not None:
                pts.append({"symbol": r["broker_code"], "net": r["net_idr"],
                            "group": group})
    if len(pts) < 2:
        return None
    sym = _sym(data.get("symbol"))
    return _spec(
        "broker_rank_bars", "diverging_bar", f"{sym} top brokers",
        {"key": "symbol", "label": "Broker", "type": "category"},
        [{"key": "net", "label": "Net IDR"}],
        pts, fetched_at, "idr",
    )


def _screen_bars(data: Any, fetched_at: str) -> dict | None:
    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        return None
    metric = next(
        (
            k
            for r in results
            if isinstance(r, dict) and isinstance(r.get("query_values"), dict)
            for k, v in r["query_values"].items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ),
        None,
    )
    if metric is None:
        return None
    pts = [
        {"symbol": _sym(r["symbol"]),
         metric: r["query_values"][metric]}
        for r in results
        if isinstance(r, dict) and r.get("symbol")
        and isinstance((r.get("query_values") or {}).get(metric), (int, float))
    ]
    if len(pts) < 2:
        return None
    label = metric.replace("_", " ")
    return _spec(
        "screen_bars", "bar", f"Screener — {label}",
        {"key": "symbol", "label": "Symbol", "type": "category"},
        [{"key": metric, "label": label}],
        pts, fetched_at, "number",
    )


def _financials_trend(data: Any, fetched_at: str) -> dict | None:
    fin = data.get("financials") if isinstance(data, dict) else None
    rows = (fin or {}).get("historical_financials") or []
    pts = [
        {"year": str(r["year"]), "revenue": r.get("revenue"),
         "earnings": r.get("earnings")}
        for r in rows
        if isinstance(r, dict) and r.get("year")
        and (r.get("revenue") is not None or r.get("earnings") is not None)
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r["year"])
    sym = _sym(data.get("symbol"))
    return _spec(
        "financials_trend", "grouped_bar",
        f"{sym} annual revenue vs earnings",
        {"key": "year", "label": "Year", "type": "category"},
        [{"key": "revenue", "label": "Revenue"},
         {"key": "earnings", "label": "Earnings"}],
        pts, fetched_at, "idr",
    )


def _peers_bars(data: Any, fetched_at: str) -> dict | None:
    peers = data.get("peers") if isinstance(data, dict) else None
    companies = (
        ((peers or [{}])[0].get("peers_data") or {}).get("companies") or []
    )
    pts = [
        {"symbol": _sym(c["symbol"]), "mcap": c["market_cap"]}
        for c in companies
        if isinstance(c, dict) and c.get("symbol")
        and c.get("market_cap") is not None
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r["mcap"], reverse=True)
    return _spec(
        "peers_bars", "bar", "Peer market cap",
        {"key": "symbol", "label": "Symbol", "type": "category"},
        [{"key": "mcap", "label": "Market cap"}],
        pts, fetched_at, "idr",
    )


def _dividend_history(data: Any, fetched_at: str) -> dict | None:
    div = data.get("dividend") if isinstance(data, dict) else None
    hist = (div or {}).get("historical_dividends") or {}
    pts = [
        {"year": y, "dividend": v.get("total_dividend")}
        for y, v in hist.items()
        if isinstance(v, dict) and v.get("total_dividend") is not None
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r["year"])
    sym = _sym(data.get("symbol"))
    return _spec(
        "dividend_history", "bar", f"{sym} dividends per year",
        {"key": "year", "label": "Year", "type": "category"},
        [{"key": "dividend", "label": "DPS (IDR)"}],
        pts, fetched_at, "number",
    )


def _valuation_trend(data: Any, fetched_at: str) -> dict | None:
    val = data.get("valuation") if isinstance(data, dict) else None
    rows = (val or {}).get("historical_valuation") or []
    pts = [
        {"year": str(r["year"]), "pe": r.get("pe"), "pb": r.get("pb"),
         "ps": r.get("ps")}
        for r in rows
        if isinstance(r, dict) and r.get("year")
        and any(r.get(k) is not None for k in ("pe", "pb", "ps"))
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r["year"])
    sym = _sym(data.get("symbol"))
    return _spec(
        "valuation_trend", "line", f"{sym} valuation multiples",
        {"key": "year", "label": "Year", "type": "category"},
        [{"key": "pe", "label": "P/E"}, {"key": "pb", "label": "P/B"},
         {"key": "ps", "label": "P/S"}],
        pts, fetched_at, "number",
    )


def _subsector_mcap_trend(data: Any, fetched_at: str) -> dict | None:
    mc = data.get("market_cap") if isinstance(data, dict) else None
    q = (mc or {}).get("quarterly_market_cap") or {}
    merged = {**(q.get("prev_ttm_mcap") or {}),
              **(q.get("current_ttm_mcap") or {})}
    pts = [{"quarter": k, "mcap": v} for k, v in merged.items()
           if v is not None]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r["quarter"])
    sub = data.get("sub_sector", "")
    return _spec(
        "subsector_mcap_trend", "area", f"{sub} market cap by quarter",
        {"key": "quarter", "label": "Quarter", "type": "category"},
        [{"key": "mcap", "label": "Market cap"}],
        pts, fetched_at, "idr",
    )


def _subsector_top_mcap(data: Any, fetched_at: str) -> dict | None:
    comps = data.get("companies") if isinstance(data, dict) else None
    top = ((comps or {}).get("top_companies") or {}).get("top_mcap") or {}
    pts = [
        {"symbol": _sym(s), "mcap": v.get("market_cap")}
        for s, v in top.items()
        if isinstance(v, dict) and v.get("market_cap") is not None
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r["mcap"], reverse=True)
    return _spec(
        "subsector_top_mcap", "bar", "Top companies by market cap",
        {"key": "symbol", "label": "Symbol", "type": "category"},
        [{"key": "mcap", "label": "Market cap"}],
        pts, fetched_at, "idr",
    )


VIEWS: dict[str, dict[str, dict[str, Any]]] = {
    "sectors_daily_prices": {
        "price_volume": {
            "desc": "Daily close-price line with volume bars over the window.",
            "extract": _price_volume,
        },
    },
    "sectors_idx_market_summary": {
        "mcap_area": {
            "desc": "Total IDX market capitalization area chart over the window.",
            "extract": _mcap_area,
        },
    },
    "sectors_foreign_flow": {
        "netflow": {
            "desc": "Daily net foreign inflow — signed area, positive = foreign buying.",
            "extract": _netflow,
        },
    },
    "sectors_quarterly_financials": {
        "quarterly_grouped": {
            "desc": "Revenue vs earnings grouped bars per quarter.",
            "extract": _quarterly_grouped,
        },
    },
    "sectors_listing_performance": {
        "perf_bars": {
            "desc": "% change since listing across 7/30/90/365-day windows.",
            "extract": _perf_bars,
        },
    },
    "sectors_top_movers": {
        "movers": {
            "desc": "Signed % change per stock for each classification/period — diverging bars.",
            "extract": _movers,
        },
    },
    "sectors_most_traded": {
        "traded_bars": {
            "desc": "Latest day's most-traded stocks by volume — ranked bars.",
            "extract": _traded_bars,
        },
        "traded_trend": {
            "desc": "Top symbols' daily volume over the whole window — multi-line trend.",
            "extract": _traded_trend,
        },
    },
    "sectors_broker_summary": {
        "broker_net_bars": {
            "desc": "Net buy/sell value per broker summed over the window — diverging bars.",
            "extract": _broker_net_bars,
        },
    },
    "sectors_broker_top": {
        "broker_rank_bars": {
            "desc": "Top buyer and top seller brokers by net IDR — diverging bars.",
            "extract": _broker_rank_bars,
        },
    },
    "sectors_screen": {
        "screen_bars": {
            "desc": "Bar chart of the screened companies on the numeric metric returned (e.g. market cap).",
            "extract": _screen_bars,
        },
    },
    "sectors_company_report": {
        "financials_trend": {
            "desc": "Annual revenue vs earnings grouped bars (financials section).",
            "extract": _financials_trend,
        },
        "peers_bars": {
            "desc": "Market cap per company in the peer group (peers section).",
            "extract": _peers_bars,
        },
        "dividend_history": {
            "desc": "Total dividend per share per year (dividend section).",
            "extract": _dividend_history,
        },
        "valuation_trend": {
            "desc": "P/E, P/B, P/S multiples by year (valuation section).",
            "extract": _valuation_trend,
        },
    },
    "sectors_subsector_report": {
        "subsector_mcap_trend": {
            "desc": "Subsector total market cap by quarter — area trend.",
            "extract": _subsector_mcap_trend,
        },
        "subsector_top_mcap": {
            "desc": "Largest companies in the subsector by market cap — bars.",
            "extract": _subsector_top_mcap,
        },
    },
}


def _preview(data: Any) -> dict[str, Any]:
    """Compact shape summary for JEV — never the full payload."""
    rows = _rows(data)
    if rows:
        return {
            "shape": "rows",
            "row_count": len(rows),
            "fields": sorted({k for r in rows[:5] for k in r}),
            "sample": rows[:3],
        }
    if isinstance(data, dict):
        return {
            "shape": "object",
            "keys": list(data)[:20],
            "sample": json.dumps(data, default=str)[:800],
        }
    return {"shape": type(data).__name__}


async def judge_and_extract(
    tool_name: str, content: Any, question: str
) -> dict | None:
    """Tool result → chart spec or None. Never raises, never spends JEV on
    tools without registered views or on broken envelopes."""
    views = VIEWS.get(tool_name)
    if not views:
        return None
    env = content
    if isinstance(content, str):
        try:
            env = json.loads(content)
        except ValueError:
            return None
    if not isinstance(env, dict):
        return None
    if env.get("status") != 200 or env.get("truncated"):
        return None
    data = env.get("data")
    if not isinstance(data, (list, dict)):
        return None

    result = await jev_ask(
        {
            "user_question": question,
            "tool": tool_name,
            "data_preview": _preview(data),
        },
        {
            "chartable": Noul(
                instructions=(
                    "Would a chart make this tool result meaningfully clearer "
                    "for the user's question — e.g. a trend over time, a "
                    "comparison across symbols, or a distribution they asked "
                    "about?"
                )
            ),
            "view": Choice(
                instructions=(
                    "Pick the single most meaningful chart view for the "
                    "user's question, or 'none' when no view fits."
                ),
                criteria={
                    **{v: d["desc"] for v, d in views.items()},
                    "none": "No chart adds clarity — the text answer is enough.",
                },
            ),
        },
    )
    if result is None:
        return None
    noul = result.nouls.get("chartable")
    if noul is None or float(noul.noul) < 0.5:
        return None
    answer = result.choices.get("view")
    view = answer.choice if answer else None
    if not view or view not in views:
        return None
    try:
        spec = views[view]["extract"](data, env.get("fetched_at", ""))
    except Exception:
        logger.exception("chart extract failed: %s/%s", tool_name, view)
        return None
    if spec is not None:
        spec["tool"] = tool_name
        spec["view"] = view
    return spec
