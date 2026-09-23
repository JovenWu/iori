"""Chart detection: JEV judges chartability + picks a view; code builds the spec.

Per tool result with registered views, one jev_ask asks in parallel whether a
chart adds clarity (Noul) and which view fits best (Choice over the tool's
registered views + "none"). Extractors are deterministic data-shapers keyed by
view — the model never writes the spec. Any failure → no chart; the turn is
never affected.
"""

import json
import logging
import re
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

_X_DATE = {"key": "date", "label": "Date", "type": "time"}


def _is_symbol_map(data: Any) -> bool:
    """Multi-symbol fan-out shape: {SYM: {status, data, ...}} — every value a
    sub-envelope dict. Single-symbol bodies always carry scalar/list fields."""
    return (
        isinstance(data, dict)
        and bool(data)
        and all(isinstance(v, dict) for v in data.values())
    )


def _pivot_by_date(data: dict, field: str) -> tuple[list[dict], list[dict]]:
    """{SYM: sub-envelope} → (series, wide rows {date, SYM: v}) so one chart
    carries one series per ticker on a shared date axis."""
    series: list[dict] = []
    by_date: dict[str, dict] = {}
    for sym, env in data.items():
        rows = _rows(env.get("data") if isinstance(env, dict) else None)
        pts = [
            (r["date"], r[field])
            for r in rows
            if r.get("date") and r.get(field) is not None
        ]
        if not pts:
            continue
        key = _sym(sym)
        series.append({"key": key, "label": key})
        for d, v in pts:
            by_date.setdefault(d, {"date": d})[key] = v
    return series, [by_date[d] for d in sorted(by_date)]


def _price_lines(data: dict, fetched_at: str) -> dict | None:
    """Multi-symbol closes → indexed (base-100) lines so different price
    scales compare fairly — the canonical comparison chart."""
    series, pts = _pivot_by_date(data, "close")
    if len(series) < 2 or len(pts) < 2:
        return None
    base = {
        s["key"]: next((r[s["key"]] for r in pts if r.get(s["key"])), None)
        for s in series
    }
    for row in pts:
        for s in series:
            k = s["key"]
            row[k] = round(row[k] / base[k] * 100, 2) if row.get(k) and base[k] else None
    label = " vs ".join(s["key"] for s in series)
    return _spec("price_volume", "line",
                 f"Indexed performance — {label} (base 100)",
                 _X_DATE, series, pts, fetched_at, "number")


def _flow_lines(data: dict, fetched_at: str) -> dict | None:
    """Multi-symbol foreign flow → one signed line per ticker, shared axis."""
    series, pts = _pivot_by_date(data, "net_foreign_inflow")
    if len(series) < 2 or len(pts) < 2:
        return None
    label = " vs ".join(s["key"] for s in series)
    return _spec("netflow", "line", f"Net foreign flow — {label}",
                 _X_DATE, series, pts, fetched_at, "idr")


def _price_volume(data: Any, fetched_at: str) -> dict | None:
    if _is_symbol_map(data):
        return _price_lines(data, fetched_at)
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
        _X_DATE,
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
        _X_DATE,
        [{"key": "mcap", "label": "Total market cap"}],
        pts, fetched_at, "idr",
    )


def _netflow(data: Any, fetched_at: str) -> dict | None:
    if _is_symbol_map(data):
        return _flow_lines(data, fetched_at)
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
        _X_DATE,
        [{"key": "net", "label": "Net foreign inflow"}],
        pts, fetched_at, "idr",
    )


def _quarterly_lines(data: dict, fetched_at: str) -> dict | None:
    """Multi-symbol quarterly fan-out → revenue + earnings line per ticker on
    one shared quarter axis (e.g. 'BBCA revenue', 'BMRI earnings')."""
    fields = ("revenue", "earnings")
    series: list[dict] = []
    by_date: dict[str, dict] = {}
    for sym, env in data.items():
        rows = _rows(env.get("data") if isinstance(env, dict) else None)
        rows = [
            r for r in rows
            if r.get("date") and any(_num(r.get(f)) for f in fields)
        ]
        if not rows:
            continue
        s = _sym(sym)
        for f in fields:
            series.append({"key": f"{s} {f}", "label": f"{s} {f}"})
        for r in rows:
            row = by_date.setdefault(r["date"], {"date": r["date"]})
            for f in fields:
                if _num(r.get(f)):
                    row[f"{s} {f}"] = r[f]
    pts = [by_date[d] for d in sorted(by_date)]
    series = [s for s in series if any(s["key"] in row for row in pts)]
    if len(series) < 2 or len(pts) < 2:
        return None
    label = " vs ".join(_sym(s) for s in data)
    return _spec("quarterly_grouped", "line",
                 f"Quarterly revenue vs earnings — {label}",
                 _X_DATE, series, pts, fetched_at, "idr")


def _quarterly_grouped(data: Any, fetched_at: str) -> dict | None:
    if _is_symbol_map(data):
        return _quarterly_lines(data, fetched_at)
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
        _X_DATE,
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


def _index_line(data: Any, fetched_at: str) -> dict | None:
    rows = _rows(data)
    pts = [
        {"date": r["date"], "price": r["price"]}
        for r in rows
        if r.get("date") and r.get("price") is not None
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r["date"])
    code = str(rows[0].get("index_code") or "").upper()
    return _spec(
        "index_line", "line", f"{code} index level",
        _X_DATE,
        [{"key": "price", "label": "Level"}],
        pts, fetched_at, "number",
    )


# -- generic fallback ---------------------------------------------------------
# Shape-driven extraction for any sectors_* result: rows → line/bars, symbol
# maps → per-ticker lines, flat numeric dicts → bars. JEV still gates whether a
# chart helps; this only shapes the spec deterministically.

_DATEISH = re.compile(r"^\d{4}([-/.]\d{1,2}){1,2}")
_TIME_KEYS = ("date", "datetime", "timestamp", "period", "quarter", "year", "month")
_CAT_KEYS = ("symbol", "broker_code", "name", "window", "group", "category",
             "sector", "sub_sector", "index_code")
# Field names that usually carry "the" metric — beats alphabetical ties.
_PREFERRED = ("net", "inflow", "close", "price", "market_cap", "mcap",
              "revenue", "earnings", "value", "volume", "total", "yield",
              "share", "change", "pct")


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _field_rank(name: str, coverage: int) -> tuple[int, int, str]:
    n = name.lower()
    pref = next((i for i, k in enumerate(_PREFERRED) if k in n), len(_PREFERRED))
    return (pref, -coverage, name)


def _numeric_fields(rows: list[dict], exclude: str) -> list[str]:
    counts: dict[str, int] = {}
    for r in rows:
        for k, v in r.items():
            if k != exclude and _num(v):
                counts[k] = counts.get(k, 0) + 1
    return sorted(counts, key=lambda k: _field_rank(k, counts[k]))


def _pick_x(rows: list[dict]) -> str | None:
    keys = {k for r in rows for k in r}
    for k in _TIME_KEYS:
        if k in keys:
            return k
    for k in sorted(keys):
        vals = [r[k] for r in rows if r.get(k) is not None][:10]
        if vals and sum(bool(_DATEISH.match(str(v))) for v in vals) / len(vals) >= 0.6:
            return k
    for k in _CAT_KEYS:
        if k in keys:
            return k
    return next(
        (k for k in sorted(keys) if any(isinstance(r.get(k), str) for r in rows)),
        None,
    )


def _fmt_guess(field: str, vals: list) -> str:
    f = field.lower()
    if any(k in f for k in ("pct", "percent", "share", "yield", "change",
                            "margin", "growth", "ratio", "float")):
        mx = max((abs(v) for v in vals if _num(v)), default=0)
        return "percent" if mx <= 1.5 else "percent_raw"
    if any(k in f for k in ("idr", "inflow", "cap", "revenue", "earnings",
                            "turnover", "amount", "val")):
        return "idr"
    return "number"


def _generic_map(data: dict, fetched_at: str) -> dict | None:
    """{SYM: sub-envelope} → per-ticker lines on the best-covered metric."""
    counts: dict[str, int] = {}
    for env in data.values():
        for r in _rows(env.get("data") if isinstance(env, dict) else None):
            for k, v in r.items():
                if _num(v):
                    counts[k] = counts.get(k, 0) + 1
    if not counts:
        return None
    field = min(counts, key=lambda k: _field_rank(k, counts[k]))
    series, pts = _pivot_by_date(data, field)
    if len(series) < 2 or len(pts) < 2:
        return None
    vals = [r[s["key"]] for r in pts for s in series if _num(r.get(s["key"]))]
    label = field.replace("_", " ")
    title = f"{label} — {' vs '.join(s['key'] for s in series)}"
    return _spec("generic", "line", title, _X_DATE, series, pts, fetched_at,
                 _fmt_guess(field, vals))


def _generic_rows(rows: list[dict], fetched_at: str) -> dict | None:
    x = _pick_x(rows)
    if x is None:
        return None
    fields = _numeric_fields(rows, exclude=x)[:4]
    if not fields:
        return None
    pts = [
        {x: str(r[x]), **{f: r.get(f) for f in fields}}
        for r in rows if r.get(x) is not None
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda r: r[x])
    temporal = x in _TIME_KEYS or bool(_DATEISH.match(pts[0][x]))
    if temporal:
        kind = "line"
    elif len(fields) > 1:
        kind = "grouped_bar"
        pts = pts[:25]
    else:
        f0 = fields[0]
        neg = any(_num(r[f0]) and r[f0] < 0 for r in pts)
        kind = "diverging_bar" if neg else "bar"
        pts = sorted(pts, key=lambda r: abs(r[f0] or 0), reverse=True)[:25]
    series = [{"key": f, "label": f.replace("_", " ")} for f in fields]
    title = f"{', '.join(s['label'] for s in series)} by {x.replace('_', ' ')}"
    return _spec(
        "generic", kind, title,
        {"key": x, "label": x.replace("_", " "),
         "type": "time" if temporal else "category"},
        series, pts, fetched_at,
        _fmt_guess(fields[0], [r.get(fields[0]) for r in pts]),
    )


def _generic(data: Any, fetched_at: str) -> dict | None:
    """Best-effort spec for shapes no named view claims."""
    if _is_symbol_map(data):
        return _generic_map(data, fetched_at)
    rows = _rows(data)
    if len(rows) >= 2:
        return _generic_rows(rows, fetched_at)
    if isinstance(data, dict):
        pts = [{"k": str(k), "v": v} for k, v in data.items() if _num(v)]
        if len(pts) < 2:
            return None
        pts = sorted(pts, key=lambda r: abs(r["v"]), reverse=True)[:25]
        kind = "diverging_bar" if any(r["v"] < 0 for r in pts) else "bar"
        return _spec("generic", kind, "Breakdown",
                     {"key": "k", "label": "", "type": "category"},
                     [{"key": "v", "label": "Value"}], pts, fetched_at,
                     _fmt_guess("", [r["v"] for r in pts]))
    return None


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
            "desc": "Daily close line + volume bars; multi-symbol calls become indexed (base-100) comparison lines.",
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
            "desc": "Daily net foreign inflow — signed area for one ticker, one line per ticker for comparisons.",
            "extract": _netflow,
        },
    },
    "sectors_quarterly_financials": {
        "quarterly_grouped": {
            "desc": "Revenue vs earnings grouped bars per quarter; multi-symbol calls become revenue+earnings lines per ticker.",
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
    "sectors_index_daily": {
        "index_line": {
            "desc": "Index closing level over the window — benchmark line.",
            "extract": _index_line,
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
    non-sectors tools or broken envelopes. Every sectors_* tool gets a
    "generic" option alongside its named views, so results with no dedicated
    view can still chart when a trend/comparison adds clarity."""
    if not tool_name.startswith("sectors_"):
        return None
    views = {
        **VIEWS.get(tool_name, {}),
        "generic": {
            "desc": "Fallback — reshape the result into a trend, comparison, or breakdown chart when no named view fits.",
            "extract": _generic,
        },
    }
    env = content
    if isinstance(content, str):
        try:
            env = json.loads(content)
        except ValueError:
            return None
    if not isinstance(env, dict):
        return None
    if env.get("status") != 200:
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
    spec = None
    try:
        spec = views[view]["extract"](data, env.get("fetched_at", ""))
    except Exception:
        logger.exception("chart extract failed: %s/%s", tool_name, view)
    if spec is None and view != "generic":
        try:
            spec = _generic(data, env.get("fetched_at", ""))
        except Exception:
            logger.exception("chart extract failed: %s/generic", tool_name)
        if spec is not None:
            view = "generic"
    if spec is not None:
        spec["tool"] = tool_name
        spec["view"] = view
    return spec
