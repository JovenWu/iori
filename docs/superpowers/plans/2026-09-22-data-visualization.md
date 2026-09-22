# Data Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically create interactive charts when agent tool calls return chartable financial data — JEV judges chartability and picks a predefined view per tool result, deterministic extractors build normalized specs, specs stream over SSE, persist in the LangGraph checkpoint, and render as recharts components in the chat UI.

**Architecture:** The prebuilt `ToolNode` is replaced by a custom `tools` node that runs the tools then calls `judge_and_extract` per result (one `jev_ask` with a `Noul` chartable gate + `Choice` view picker; deterministic extractors do the data shaping). Specs accumulate in `ChatState.charts` (anchor = ToolMessage index), emit as `chart` SSE events, and `get_thread_messages` attaches each chart to the assistant message that closed its turn. Frontend renders `Message.charts` via a `ChartBlock` dispatcher → generic kind renderers.

**Tech Stack:** Python 3.12 / LangGraph / typesafe-sdk JEV (existing `app.core.jev`), pytest; Next.js 16 + React 19 + Tailwind v4 + recharts (new dep).

**Spec:** `docs/superpowers/specs/2026-09-22-data-visualization-design.md`

## Global Constraints

- **Commit gate:** user reviews before EVERY commit — pause and ask, never commit unreviewed work.
- Commit style: lowercase `phase 11<x>: short description` (lettered sub-phases like `7a`/`8c`). No `Co-Authored-By`/`Generated with` trailers — commits are authored by the user only.
- Backend tests run in docker: `docker compose exec backend python -m pytest tests`.
- Frontend checks: `docker compose exec frontend npx tsc --noEmit`, `docker compose exec frontend npx eslint .`, `docker compose exec frontend npm run build`.
- `/app/node_modules` is a container-side anonymous volume — dependency changes need `docker compose up -d --build frontend` (per docker-compose.yml comment).
- Design: dark-first theme, lavender accent (`var(--primary)` = #5e6ad2), no bright/yellow accents. CSS vars (`var(--primary)`, `var(--muted-foreground)`, `var(--border)`, `var(--popover)`, `var(--destructive)`) work as SVG props in recharts.
- Next.js 16 has breaking changes — if touching Next-specific APIs, read `frontend/node_modules/next/dist/docs/` first. Chart components are plain `"use client"` components, low risk.
- JEV fallback contract: `jev_ask` returns `None` when unconfigured/failed — every call site must degrade gracefully (see `app/core/jev.py` docstring).
- After code changes, run `/code-simplifier` audit before finishing (project rule).

## Spec schema (shared contract for all tasks)

```python
# backend — dict appended to state["charts"]
{
    "id": str,            # uuid hex[:12]
    "tool": str,          # "sectors_daily_prices"
    "view": str,          # registry key, e.g. "price_volume"
    "kind": str,          # line|area|signed_area|bar|diverging_bar|grouped_bar|price_volume
    "title": str,
    "x": {"key": str, "label": str, "type": "time"|"category"},
    "series": [{"key": str, "label": str}],
    "data": [dict],       # rows; may carry optional "group" for sectioning
    "fetched_at": str,    # envelope fetched_at — rendered as caption
    "format": str,        # "percent"|"percent_raw"|"idr"|"number"
    "anchor": int,        # backend-internal: index of the ToolMessage in state["messages"]
}
```

`format`: `"percent"` multiplies ratios ×100 (top_movers `price_change` is a ratio like 0.25); `"percent_raw"` prints the value as-is (listing_performance `chg_*` is already in percent units); `"idr"`/`"number"` use compact T/B/M/K.

## Verified upstream data shapes (docs.sectors.app — do not guess these)

- `sectors_daily_prices` → `data`: `[{symbol, date, close, open, high, low, volume, market_cap}]`
- `sectors_top_movers` → `data`: `{top_gainers|top_losers: {"1d"|"7d"|"14d"|"30d"|"365d": [{name, symbol, price_change, last_close_price, latest_close_date}]}}`
- `sectors_most_traded` → `data`: `{"YYYY-MM-DD": [{symbol, company_name, volume, price}]}`
- `sectors_idx_market_summary` → `data`: `[{date, idx_total_market_cap}]`
- `sectors_foreign_flow` → `data`: `{symbol, start, end, data: [{date, net_foreign_inflow, foreign_buy_idr, foreign_sell_idr, foreign_share}]}`
- `sectors_quarterly_financials` → `data`: `[{symbol, date, revenue, earnings, ...many nullable fields, financials_sector_metrics}]`
- `sectors_broker_summary` → `data`: `{symbol, start, end, data: [{date, summary: [{broker_code, bval, sval, nval, nlot, ...}]}]}`
- `sectors_broker_top` → `data`: `{symbol, top_buyers: [{rank, broker_code, net_idr, buy_idr, sell_idr, foreign_net_idr}], top_sellers: [same]}`
- `sectors_listing_performance` → `data`: `{symbol, company_name, chg_7d, chg_30d, chg_90d, chg_365d, offering_price, listing_date, ...}` (chg_* already in percent)
- `sectors_screen` → `data`: `{results: [{symbol, company_name, query_values?}], pagination, llm_translation}` — `query_values` present ONLY when `include_query_values=true` (Task 3 adds it)
- `sectors_company_report` → `data`: `{symbol, company_name, overview?, valuation?, future?, financials?, dividend?, management?, ownership?, peers?}` where `financials.historical_financials` = `[{year, revenue, earnings, ...}]`, `peers` = `[{peers_data: {companies: [{symbol, company_name, market_cap, net_income, ...}]}}]`, `dividend.historical_dividends` = `{"YYYY": {breakdown, total_yield, total_dividend}}`, `valuation.historical_valuation` = `[{year, pb, pe, ps, pcf, peg, pb_peer_avg, ...}]`
- `sectors_subsector_report` → `data`: `{sector, sub_sector, statistics?, market_cap?, stability?, valuation?, growth?, companies?}` where `market_cap.quarterly_market_cap` = `{prev_ttm_mcap: {"2024.Q3": n}, current_ttm_mcap: {...}}` and `companies.top_companies.top_mcap` = `{SYMBOL: {name, market_cap}}`
- Not chartable (no registered views, skipped before JEV): `sectors_list_subsectors` (`[{sector, subsector}]` — no numeric fields), `sectors_news`, `sectors_insider_filings`, `sectors_suspensions`, `sectors_corporate_actions`

---

### Task 1: `app/sectors/charts.py` — spec builder, JEV judge, registry, first extractor

**Files:**
- Create: `backend/app/sectors/charts.py`
- Test: `backend/tests/test_charts.py`

**Interfaces:**
- Consumes: `app.core.jev.jev_ask`, `Choice`, `Noul` (same usage as `app/agent/router.py`)
- Produces:
  - `judge_and_extract(tool_name: str, content: Any, question: str) -> dict | None` — entry point used by the tools node (Task 5). `content` is the ToolMessage's string content (JSON envelope).
  - `VIEWS: dict[str, dict[str, dict]]` — `{tool_name: {view_key: {"desc": str, "extract": callable}}}`; extractors take `(data: Any, fetched_at: str) -> dict | None` and return the spec WITHOUT `tool`/`anchor` (judge fills them).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_charts.py
"""Chart detection: JEV gate + view pick, deterministic extractors."""

import json
from types import SimpleNamespace

import pytest

from app.sectors import charts

pytestmark = pytest.mark.asyncio


def _envelope(data, status=200, **extra):
    return json.dumps(
        {"status": status, "source": "upstream", "stale": False,
         "fetched_at": "2026-09-21T17:00:00", "data": data, **extra}
    )


def _resp(noul=1.0, view="price_volume"):
    return SimpleNamespace(
        nouls={"chartable": SimpleNamespace(noul=noul)},
        choices={"view": SimpleNamespace(choice=view)},
    )


DAILY = [
    {"symbol": "BBCA.JK", "date": "2026-09-17", "close": 6200,
     "open": 6175, "high": 6250, "low": 6150, "volume": 9000000,
     "market_cap": 7.5e14},
    {"symbol": "BBCA.JK", "date": "2026-09-18", "close": 6175,
     "open": 6200, "high": 6225, "low": 6100, "volume": 11000000,
     "market_cap": 7.4e14},
    {"symbol": "BBCA.JK", "date": "2026-09-21", "close": 6300,
     "open": 6180, "high": 6325, "low": 6150, "volume": 12000000,
     "market_cap": 7.6e14},
]


async def test_judge_builds_price_volume_spec(monkeypatch):
    async def fake_ask(state, questions):
        assert "chartable" in questions and "view" in questions
        assert "none" in questions["view"].criteria
        return _resp(view="price_volume")

    monkeypatch.setattr(charts, "jev_ask", fake_ask)
    spec = await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(DAILY), "harga BBCA sebulan"
    )
    assert spec is not None
    assert spec["view"] == "price_volume" and spec["kind"] == "price_volume"
    assert spec["tool"] == "sectors_daily_prices"
    assert spec["x"] == {"key": "date", "label": "Date", "type": "time"}
    assert [p["close"] for p in spec["data"]] == [6200, 6175, 6300]
    assert spec["fetched_at"] == "2026-09-21T17:00:00"


async def test_unregistered_tool_never_calls_jev(monkeypatch):
    async def boom(state, questions):
        raise AssertionError("jev_ask must not run for unchartable tools")

    monkeypatch.setattr(charts, "jev_ask", boom)
    assert await charts.judge_and_extract("sectors_news", _envelope({}), "x") is None


async def test_bad_envelopes_skip(monkeypatch):
    async def boom(state, questions):
        raise AssertionError("must skip before JEV")

    monkeypatch.setattr(charts, "jev_ask", boom)
    assert await charts.judge_and_extract(
        "sectors_daily_prices", '{"error": "sectors_api_unavailable"}', "x"
    ) is None
    assert await charts.judge_and_extract(
        "sectors_daily_prices", "not json", "x"
    ) is None
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(DAILY, truncated=True), "x"
    ) is None
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope({"error": "nf"}, status=404), "x"
    ) is None


async def test_jev_none_or_low_noul_or_none_view(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", lambda s, q: None)
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(DAILY), "x"
    ) is None

    async def low(state, questions):
        return _resp(noul=0.2)

    monkeypatch.setattr(charts, "jev_ask", low)
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(DAILY), "x"
    ) is None

    async def none_view(state, questions):
        return _resp(view="none")

    monkeypatch.setattr(charts, "jev_ask", none_view)
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(DAILY), "x"
    ) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend python -m pytest tests/test_charts.py -v`
Expected: FAIL — `ModuleNotFoundError: app.sectors.charts`

- [ ] **Step 3: Implement `backend/app/sectors/charts.py`**

```python
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
    sym = str(rows[0].get("symbol", "")).removesuffix(".JK")
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


VIEWS: dict[str, dict[str, dict[str, Any]]] = {
    "sectors_daily_prices": {
        "price_volume": {
            "desc": "Daily close-price line with volume bars over the window.",
            "extract": _price_volume,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend python -m pytest tests/test_charts.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit (after user review)**

```bash
git add backend/app/sectors/charts.py backend/tests/test_charts.py
git commit -m "phase 11a: chart spec registry + jev chartability judge"
```

---

### Task 2: Time-series extractors (mcap_area, netflow, quarterly_grouped, perf_bars)

**Files:**
- Modify: `backend/app/sectors/charts.py`
- Test: `backend/tests/test_charts.py`

**Interfaces:**
- Consumes: `_rows`, `_spec`, `VIEWS` from Task 1
- Produces: four more `VIEWS` entries — same `(data, fetched_at) -> dict | None` signature

- [ ] **Step 1: Write the failing tests** (append to `test_charts.py`)

```python
IDX_TOTAL = [
    {"date": "2026-09-17", "idx_total_market_cap": 1.0e16},
    {"date": "2026-09-18", "idx_total_market_cap": 1.01e16},
    {"date": "2026-09-21", "idx_total_market_cap": 1.02e16},
]

FOREIGN_FLOW = {
    "symbol": "BBCA.JK", "start": "2026-09-15", "end": "2026-09-21",
    "data": [
        {"date": "2026-09-17", "net_foreign_inflow": 1.4e11,
         "foreign_buy_idr": 5.5e11, "foreign_sell_idr": 4.1e11,
         "foreign_share": 0.58},
        {"date": "2026-09-18", "net_foreign_inflow": -2.0e10,
         "foreign_buy_idr": 4.0e11, "foreign_sell_idr": 4.2e11,
         "foreign_share": 0.51},
        {"date": "2026-09-21", "net_foreign_inflow": 3.0e10,
         "foreign_buy_idr": 6.0e11, "foreign_sell_idr": 5.7e11,
         "foreign_share": 0.55},
    ],
}

QUARTERLY = [
    {"symbol": "BBCA.JK", "date": "2026-03-31", "revenue": 2.8e13,
     "earnings": 1.47e13},
    {"symbol": "BBCA.JK", "date": "2026-06-30", "revenue": 2.9e13,
     "earnings": 1.5e13},
    {"symbol": "BBCA.JK", "date": "2026-09-30", "revenue": 3.0e13,
     "earnings": 1.6e13},
]

LISTING_PERF = {
    "symbol": "BREN.JK", "company_name": "PT Barito Renewables Energy Tbk.",
    "chg_7d": 2.53, "chg_30d": 4.64, "chg_90d": 8.26, "chg_365d": 7.59,
    "offering_price": 780, "listing_date": "2023-10-09",
}


async def test_mcap_area(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("mcap_area"))
    spec = await charts.judge_and_extract(
        "sectors_idx_market_summary", _envelope(IDX_TOTAL), "total mcap"
    )
    assert spec["kind"] == "area" and spec["format"] == "idr"
    assert spec["data"][0]["mcap"] == 1.0e16


async def test_netflow_signed_area(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("netflow"))
    spec = await charts.judge_and_extract(
        "sectors_foreign_flow", _envelope(FOREIGN_FLOW), "foreign flow BBCA"
    )
    assert spec["kind"] == "signed_area" and spec["format"] == "idr"
    assert [p["net"] for p in spec["data"]] == [1.4e11, -2.0e10, 3.0e10]


async def test_quarterly_grouped_bars(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("quarterly_grouped"))
    spec = await charts.judge_and_extract(
        "sectors_quarterly_financials", _envelope(QUARTERLY), "BBCA quarters"
    )
    assert spec["kind"] == "grouped_bar"
    assert {s["key"] for s in spec["series"]} == {"revenue", "earnings"}


async def test_listing_perf_bars(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("perf_bars"))
    spec = await charts.judge_and_extract(
        "sectors_listing_performance", _envelope(LISTING_PERF), "BREN ipo"
    )
    assert spec["kind"] == "bar" and spec["format"] == "percent_raw"
    assert [p["window"] for p in spec["data"]] == ["7d", "30d", "90d", "365d"]


async def test_too_few_points_returns_none(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("price_volume"))
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(DAILY[:1]), "x"
    ) is None
```

Also add this helper near the top of the test file (used by these and later tests):

```python
def _view(view, noul=1.0):
    """Factory: async jev_ask fake that approves and picks `view`."""
    async def fake(state, questions):
        return _resp(noul=noul, view=view)
    return fake
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend python -m pytest tests/test_charts.py -v`
Expected: FAIL — `KeyError: 'mcap_area'` / view not in VIEWS → `spec` is `None` → `TypeError: 'NoneType' object is not subscriptable`

- [ ] **Step 3: Add extractors + registry entries to `charts.py`**

```python
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
    sym = str(data.get("symbol", "")).removesuffix(".JK") if isinstance(data, dict) else ""
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
    sym = str(rows[0].get("symbol", "")).removesuffix(".JK")
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
    sym = str(data.get("symbol", "")).removesuffix(".JK")
    return _spec(
        "perf_bars", "bar", f"{sym} performance since listing",
        {"key": "window", "label": "Window", "type": "category"},
        [{"key": "change", "label": "% change"}],
        pts, fetched_at, "percent_raw",
    )
```

And extend `VIEWS`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `docker compose exec backend python -m pytest tests/test_charts.py -v`
Expected: all pass

- [ ] **Step 5: Commit (after user review)**

```bash
git add backend/app/sectors/charts.py backend/tests/test_charts.py
git commit -m "phase 11b: time-series chart extractors"
```

---

### Task 3: Ranking extractors + screener `include_query_values`

**Files:**
- Modify: `backend/app/sectors/charts.py`
- Modify: `backend/app/sectors/tools.py` (one line in `sectors_screen`)
- Test: `backend/tests/test_charts.py`

**Interfaces:**
- Consumes: `_rows`, `_spec`, `VIEWS`
- Produces: `VIEWS` entries for `sectors_top_movers`, `sectors_most_traded`, `sectors_broker_summary`, `sectors_broker_top`, `sectors_screen`

- [ ] **Step 1: Write the failing tests** (append to `test_charts.py`)

```python
TOP_MOVERS = {
    "top_gainers": {
        "1d": [
            {"name": "PT Nitrasanata Dharma Tbk", "symbol": "JECX.JK",
             "price_change": 0.25, "last_close_price": 1950,
             "latest_close_date": "2026-09-18"},
            {"name": "PT Samator Indo Gas Tbk", "symbol": "AGII.JK",
             "price_change": 0.12, "last_close_price": 2200,
             "latest_close_date": "2026-09-18"},
        ]
    },
    "top_losers": {
        "1d": [
            {"name": "PT Contoh Tbk", "symbol": "CNTO.JK",
             "price_change": -0.18, "last_close_price": 900,
             "latest_close_date": "2026-09-18"},
            {"name": "PT Turun Tbk", "symbol": "TRUN.JK",
             "price_change": -0.11, "last_close_price": 500,
             "latest_close_date": "2026-09-18"},
        ]
    },
}

MOST_TRADED = {
    "2026-09-18": [
        {"symbol": "GOTO.JK", "company_name": "PT GoTo", "volume": 2.6e9,
         "price": 82},
        {"symbol": "DEWA.JK", "company_name": "Darma Henwa", "volume": 1.5e9,
         "price": 138},
    ],
    "2026-09-21": [
        {"symbol": "GOTO.JK", "company_name": "PT GoTo", "volume": 3.0e9,
         "price": 84},
        {"symbol": "BRMS.JK", "company_name": "Bumi Resources", "volume": 2.1e9,
         "price": 190},
    ],
    "2026-09-22": [
        {"symbol": "GOTO.JK", "company_name": "PT GoTo", "volume": 1.0e9,
         "price": 85},
        {"symbol": "DEWA.JK", "company_name": "Darma Henwa", "volume": 1.2e9,
         "price": 140},
    ],
}

BROKER_SUMMARY = {
    "symbol": "BBCA.JK", "start": "2026-09-08", "end": "2026-09-21",
    "data": [
        {"date": "2026-09-18",
         "summary": [
             {"broker_code": "KZ", "bval": 1.1e12, "sval": 5.0e11,
              "nval": 6.0e11, "nlot": 100, "bfreq": 5, "sfreq": 3,
              "blot": 120, "slot": 20},
             {"broker_code": "BK", "bval": 5.0e11, "sval": 8.0e11,
              "nval": -3.0e11, "nlot": -30, "bfreq": 4, "sfreq": 6,
              "blot": 50, "slot": 80},
         ]},
        {"date": "2026-09-21",
         "summary": [
             {"broker_code": "KZ", "bval": 5.0e11, "sval": 1.0e11,
              "nval": 4.0e11, "nlot": 40, "bfreq": 2, "sfreq": 1,
              "blot": 60, "slot": 20},
             {"broker_code": "CC", "bval": 2.0e11, "sval": 4.5e11,
              "nval": -2.5e11, "nlot": -25, "bfreq": 3, "sfreq": 5,
              "blot": 20, "slot": 45},
         ]},
    ],
}

BROKER_TOP = {
    "symbol": "BBCA.JK", "start": "2026-08-22", "end": "2026-09-21",
    "origin": "all", "cohort": "all", "foreign": False,
    "top_buyers": [
        {"rank": 1, "broker_code": "KZ", "net_idr": 6.4e11,
         "buy_idr": 1.16e12, "sell_idr": 5.1e11, "foreign_net_idr": 6.8e11},
        {"rank": 2, "broker_code": "YU", "net_idr": 3.0e11,
         "buy_idr": 6.0e11, "sell_idr": 3.0e11, "foreign_net_idr": 1.0e11},
    ],
    "top_sellers": [
        {"rank": 1, "broker_code": "BK", "net_idr": -3.1e11,
         "buy_idr": 5.6e11, "sell_idr": 8.8e11, "foreign_net_idr": -3.3e11},
        {"rank": 2, "broker_code": "MG", "net_idr": -1.0e11,
         "buy_idr": 2.0e11, "sell_idr": 3.0e11, "foreign_net_idr": -0.5e11},
    ],
}

SCREEN = {
    "results": [
        {"symbol": "BBCA.JK", "company_name": "PT Bank Central Asia Tbk.",
         "query_values": {"sub_sector": "Banks", "market_cap": 7.5e14}},
        {"symbol": "BBRI.JK", "company_name": "PT Bank Rakyat",
         "query_values": {"sub_sector": "Banks", "market_cap": 4.1e14}},
        {"symbol": "BMRI.JK", "company_name": "PT Bank Mandiri",
         "query_values": {"sub_sector": "Banks", "market_cap": 3.6e14}},
    ],
    "pagination": {"total_count": 48, "showing": 3},
    "llm_translation": {"natural_query": "top banks", "translated_params": {},
                        "message": None},
}


async def test_movers_diverging_with_groups(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("movers"))
    spec = await charts.judge_and_extract(
        "sectors_top_movers", _envelope(TOP_MOVERS), "top movers"
    )
    assert spec["kind"] == "diverging_bar" and spec["format"] == "percent"
    groups = {p["group"] for p in spec["data"]}
    assert groups == {"Top gainers 1d", "Top losers 1d"}
    assert spec["data"][0]["symbol"] == "JECX"  # .JK stripped


async def test_traded_bars_latest_day(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("traded_bars"))
    spec = await charts.judge_and_extract(
        "sectors_most_traded", _envelope(MOST_TRADED), "most traded today"
    )
    assert spec["kind"] == "bar"
    assert "2026-09-22" in spec["title"]
    assert [p["symbol"] for p in spec["data"]] == ["GOTO", "DEWA"]


async def test_traded_trend_multi_series(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("traded_trend"))
    spec = await charts.judge_and_extract(
        "sectors_most_traded", _envelope(MOST_TRADED), "volume trend"
    )
    assert spec["kind"] == "line"
    keys = {s["key"] for s in spec["series"]}
    assert keys <= {"GOTO", "DEWA", "BRMS"}
    assert spec["data"][0]["date"] == "2026-09-18"


async def test_broker_net_bars_aggregates(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("broker_net_bars"))
    spec = await charts.judge_and_extract(
        "sectors_broker_summary", _envelope(BROKER_SUMMARY), "siapa net buy"
    )
    assert spec["kind"] == "diverging_bar" and spec["format"] == "idr"
    nets = {p["symbol"]: p["net"] for p in spec["data"]}
    assert nets["KZ"] == 6.0e11 + 4.0e11
    assert nets["BK"] == -3.0e11


async def test_broker_rank_bars(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("broker_rank_bars"))
    spec = await charts.judge_and_extract(
        "sectors_broker_top", _envelope(BROKER_TOP), "top brokers BBCA"
    )
    assert spec["kind"] == "diverging_bar"
    groups = {p["group"] for p in spec["data"]}
    assert groups == {"Top buyers", "Top sellers"}


async def test_screen_bars_first_numeric_metric(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("screen_bars"))
    spec = await charts.judge_and_extract(
        "sectors_screen", _envelope(SCREEN), "top banks by mcap"
    )
    assert spec["kind"] == "bar"
    assert spec["series"][0]["key"] == "market_cap"
    assert spec["data"][0]["market_cap"] == 7.5e14


async def test_screen_without_query_values_returns_none(monkeypatch):
    bare = {"results": [{"symbol": "BBCA.JK", "company_name": "x"}]}
    monkeypatch.setattr(charts, "jev_ask", _view("screen_bars"))
    assert await charts.judge_and_extract(
        "sectors_screen", _envelope(bare), "x"
    ) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend python -m pytest tests/test_charts.py -v`
Expected: FAIL — specs `None`

- [ ] **Step 3: Implement extractors + registry entries + tool param**

In `charts.py`, append extractors:

```python
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
                        "symbol": str(r["symbol"]).removesuffix(".JK"),
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
        {"symbol": str(r["symbol"]).removesuffix(".JK"), "volume": r["volume"]}
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
            row[str(s).removesuffix(".JK")] = vols.get(s)
        pts.append(row)
    return _spec(
        "traded_trend", "line", "Most-traded volume by day",
        {"key": "date", "label": "Date", "type": "time"},
        [{"key": s.removesuffix(".JK"), "label": s.removesuffix(".JK")}
         for s in top],
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
    sym = str(data.get("symbol", "")).removesuffix(".JK")
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
    sym = str(data.get("symbol", "")).removesuffix(".JK")
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
        {"symbol": str(r["symbol"]).removesuffix(".JK"),
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
```

Registry additions:

```python
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
```

In `backend/app/sectors/tools.py`, `sectors_screen`, add `include_query_values` so `query_values` (the numeric metrics charts need — and richer agent context) comes back:

```python
    params: dict[str, Any] = {
        "order_by": order_by,
        "desc": desc,
        "limit": max(1, min(limit, 50)),
        "include_query_values": True,
    }
```

- [ ] **Step 4: Run tests**

Run: `docker compose exec backend python -m pytest tests/test_charts.py tests/test_sectors_tools.py -v`
Expected: all pass (the tools test asserts params pass-through — verify the new param doesn't break `test_sectors_tools.py`; update its expected params dict if it asserts on them)

- [ ] **Step 5: Commit (after user review)**

```bash
git add backend/app/sectors/charts.py backend/app/sectors/tools.py backend/tests/test_charts.py backend/tests/test_sectors_tools.py
git commit -m "phase 11c: ranking chart extractors, screener query values"
```

---

### Task 4: Report extractors (company + subsector reports)

**Files:**
- Modify: `backend/app/sectors/charts.py`
- Test: `backend/tests/test_charts.py`

**Interfaces:**
- Produces: `VIEWS` entries for `sectors_company_report` (`financials_trend`, `peers_bars`, `dividend_history`, `valuation_trend`) and `sectors_subsector_report` (`subsector_mcap_trend`, `subsector_top_mcap`)

- [ ] **Step 1: Write the failing tests** (append to `test_charts.py`)

```python
COMPANY_REPORT = {
    "symbol": "BBCA.JK", "company_name": "PT Bank Central Asia Tbk.",
    "financials": {
        "historical_financials": [
            {"year": 2023, "revenue": 9.0e13, "earnings": 4.5e13},
            {"year": 2024, "revenue": 1.0e14, "earnings": 5.0e13},
            {"year": 2025, "revenue": 1.1e14, "earnings": 5.7e13},
        ],
    },
    "peers": [
        {"peers_data": {"companies": [
            {"symbol": "BBCA.JK", "company_name": "BCA",
             "market_cap": 7.6e14, "net_income": 5.7e13},
            {"symbol": "BBRI.JK", "company_name": "BRI",
             "market_cap": 4.1e14, "net_income": 5.9e13},
            {"symbol": "BMRI.JK", "company_name": "Mandiri",
             "market_cap": 3.6e14, "net_income": 6.7e13},
        ]}, "group_name": {"sector": "Financials"}}
    ],
    "dividend": {
        "historical_dividends": {
            "2024": {"breakdown": [], "total_yield": 0.03,
                     "total_dividend": 280},
            "2025": {"breakdown": [], "total_yield": 0.04,
                     "total_dividend": 295},
            "2026": {"breakdown": [], "total_yield": 0.05,
                     "total_dividend": 301},
        },
        "yield_ttm": 0.05,
    },
    "valuation": {
        "historical_valuation": [
            {"year": 2023, "pb": 4.5, "pe": 24.0, "ps": 11.0},
            {"year": 2024, "pb": 4.6, "pe": 25.0, "ps": 11.5},
            {"year": 2025, "pb": 4.7, "pe": 25.6, "ps": 11.9},
        ],
    },
}

SUBSECTOR_REPORT = {
    "sector": "Financials", "sub_sector": "Banks",
    "market_cap": {
        "total_market_cap": 2.2e15,
        "quarterly_market_cap": {
            "prev_ttm_mcap": {"2025.Q3": 3.5e15, "2025.Q4": 3.1e15},
            "current_ttm_mcap": {"2026.Q1": 2.9e15, "2026.Q2": 2.8e15},
        },
    },
    "companies": {
        "top_companies": {
            "top_mcap": {
                "BBCA.JK": {"name": "BCA", "market_cap": 7.5e14},
                "BBRI.JK": {"name": "BRI", "market_cap": 4.1e14},
                "BMRI.JK": {"name": "Mandiri", "market_cap": 3.6e14},
            },
        },
    },
}


@pytest.mark.parametrize("view,kind", [
    ("financials_trend", "grouped_bar"),
    ("peers_bars", "bar"),
    ("dividend_history", "bar"),
    ("valuation_trend", "line"),
])
async def test_company_report_views(monkeypatch, view, kind):
    monkeypatch.setattr(charts, "jev_ask", _view(view))
    spec = await charts.judge_and_extract(
        "sectors_company_report", _envelope(COMPANY_REPORT), "laporan BBCA"
    )
    assert spec is not None and spec["kind"] == kind
    assert len(spec["data"]) == 3


async def test_subsector_views(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("subsector_mcap_trend"))
    spec = await charts.judge_and_extract(
        "sectors_subsector_report", _envelope(SUBSECTOR_REPORT), "tren banks"
    )
    assert spec["kind"] == "area" and spec["format"] == "idr"
    assert [p["quarter"] for p in spec["data"]] == [
        "2025.Q3", "2025.Q4", "2026.Q1", "2026.Q2"
    ]

    monkeypatch.setattr(charts, "jev_ask", _view("subsector_top_mcap"))
    spec = await charts.judge_and_extract(
        "sectors_subsector_report", _envelope(SUBSECTOR_REPORT), "terbesar"
    )
    assert spec["kind"] == "bar"
    assert spec["data"][0]["symbol"] == "BBCA"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend python -m pytest tests/test_charts.py -v`
Expected: FAIL — specs `None`

- [ ] **Step 3: Implement extractors + registry entries**

```python
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
    sym = str(data.get("symbol", "")).removesuffix(".JK")
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
        {"symbol": str(c["symbol"]).removesuffix(".JK"),
         "mcap": c["market_cap"]}
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
    sym = str(data.get("symbol", "")).removesuffix(".JK")
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
    sym = str(data.get("symbol", "")).removesuffix(".JK")
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
        {"symbol": s.removesuffix(".JK"), "mcap": v.get("market_cap")}
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
```

Registry additions:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `docker compose exec backend python -m pytest tests/test_charts.py -v`
Expected: all pass

- [ ] **Step 5: Commit (after user review)**

```bash
git add backend/app/sectors/charts.py backend/tests/test_charts.py
git commit -m "phase 11d: report chart extractors"
```

---

### Task 5: Graph wiring — `charts` state field + custom tools node

**Files:**
- Modify: `backend/app/agent/state.py`
- Create: `backend/app/agent/tools_node.py`
- Modify: `backend/app/agent/graph.py`
- Test: `backend/tests/test_agent_graph.py` (add a test), `backend/tests/test_agent_tools_node.py` (new)

**Interfaces:**
- Consumes: `judge_and_extract` from Task 1, `ToolNode(TOOLS)` behavior
- Produces: `tools` node (async fn) for `graph.add_node("tools", tools)`; `ChatState.charts` accumulating field

- [ ] **Step 1: Write the failing test** — new `backend/tests/test_agent_tools_node.py`

```python
"""Tools node: ToolNode passthrough + chart judging per ToolMessage."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import tools_node

pytestmark = pytest.mark.asyncio


def _state_with_tool_call():
    return {
        "messages": [
            HumanMessage(content="harga BBCA"),
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "sectors_daily_prices",
                    "args": {"symbol": "BBCA"},
                    "id": "call-1",
                    "type": "tool_call",
                }],
            ),
        ],
        "charts": [],
    }


async def test_charts_appended_with_anchor(monkeypatch):
    spec = {"id": "x", "view": "price_volume", "kind": "price_volume",
            "title": "t", "x": {}, "series": [], "data": [],
            "fetched_at": "", "format": "number"}
    judge = AsyncMock(return_value=spec)
    monkeypatch.setattr(tools_node, "judge_and_extract", judge)

    async def fake_tool_node(state, config=None):
        return {
            "messages": [
                ToolMessage(content="{}", tool_call_id="call-1",
                            name="sectors_daily_prices")
            ]
        }

    monkeypatch.setattr(tools_node, "_tool_node",
                        SimpleNamespace(ainvoke=fake_tool_node))
    result = await tools_node.tools(_state_with_tool_call(), {})

    assert len(result["charts"]) == 1
    # anchor = index of the ToolMessage in the full history:
    # human(0), ai tool_call(1), tool(2)
    assert result["charts"][0]["anchor"] == 2
    judge.assert_awaited_once()
    assert judge.await_args.args[0] == "sectors_daily_prices"
    assert judge.await_args.args[2] == "harga BBCA"  # the question


async def test_no_spec_no_charts_key(monkeypatch):
    monkeypatch.setattr(tools_node, "judge_and_extract",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(
        tools_node, "_tool_node",
        SimpleNamespace(ainvoke=AsyncMock(return_value={
            "messages": [ToolMessage(content="{}", tool_call_id="c",
                                     name="sectors_news")]
        })),
    )
    result = await tools_node.tools(_state_with_tool_call(), {})
    assert "charts" not in result or result.get("charts") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend python -m pytest tests/test_agent_tools_node.py -v`
Expected: FAIL — `ModuleNotFoundError: app.agent.tools_node`

- [ ] **Step 3: Implement**

`backend/app/agent/state.py` — add the accumulating field:

```python
"""Graph state.

`messages` is the full, never-trimmed history (add_messages appends).
`summarized_upto` is an index into it — everything before that index is
already folded into `summary`, so the agent only ever reads the tail.
Retrieved context lives in dedicated fields and is composed into the system
prompt per turn instead of being persisted as chat history.
`charts` accumulates chart specs produced by tool results; each spec's
`anchor` is the index of its ToolMessage so history serialization can attach
it to the assistant message that closed the turn.
"""

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    summary: str
    summarized_upto: int
    # Router output — which registered workflow owns this turn.
    workflow: str
    # Read-only context blocks composed into the system prompt per turn.
    recalled_memories: str
    related_threads: str
    # Chart specs produced by the tools node (see app/sectors/charts.py).
    charts: Annotated[list[dict[str, Any]], operator.add]
```

New `backend/app/agent/tools_node.py`:

```python
"""Tools node: run the sectors tools, then judge each result for a chart.

Wraps the prebuilt ToolNode — for every ToolMessage it produced, JEV decides
whether a chart adds clarity and which registered view fits; deterministic
extractors build the spec. Specs accumulate in `charts` (add reducer) with
`anchor` = the ToolMessage's index in the full history, so the API layer can
attach each chart to the assistant message that closes the turn.
"""

import logging
from typing import Sequence

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode

from app.agent.state import ChatState
from app.sectors.charts import judge_and_extract
from app.sectors.tools import TOOLS

logger = logging.getLogger(__name__)

_tool_node = ToolNode(TOOLS)


def _last_user_query(messages: Sequence[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            return m.content
    return ""


async def tools(state: ChatState, config: RunnableConfig) -> dict:
    result = await _tool_node.ainvoke(state, config)
    new_msgs = result.get("messages", [])
    base = len(state.get("messages", []))
    question = _last_user_query(state.get("messages", []))

    specs = []
    for i, m in enumerate(new_msgs):
        if not isinstance(m, ToolMessage):
            continue
        spec = await judge_and_extract(m.name or "", m.content, question)
        if spec is not None:
            spec["anchor"] = base + i
            specs.append(spec)
    if specs:
        result["charts"] = specs
    return result
```

`backend/app/agent/graph.py` — swap the node (and fix the stale docstring):

```python
"""Graph assembly.

START → context_manager → router → agent ⇄ tools → END

The tools node wraps ToolNode: after executing sectors_* calls it judges
each result for chartability (JEV) and appends chart specs to `charts`.
Compile happens in the service layer so it can attach the Postgres
checkpointer and run registry.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition

from app.agent.context import context_manager
from app.agent.nodes import agent
from app.agent.router import router
from app.agent.state import ChatState
from app.agent.tools_node import tools


def build_graph() -> StateGraph:
    graph = StateGraph(ChatState)
    graph.add_node("context_manager", context_manager)
    graph.add_node("router", router)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_edge(START, "context_manager")
    graph.add_edge("context_manager", "router")
    graph.add_edge("router", "agent")
    graph.add_conditional_edges(
        "agent", tools_condition, {"tools": "tools", END: END}
    )
    graph.add_edge("tools", "agent")
    return graph
```

- [ ] **Step 4: Run tests**

Run: `docker compose exec backend python -m pytest tests/test_agent_tools_node.py tests/test_agent_graph.py -v`
Expected: all pass. NOTE: `test_agent_graph.py` compiles the graph — the real `tools` node will call `judge_and_extract`, which hits `app.sectors.charts.jev_ask`. With no `TYPESAFE_API_KEY` in tests, `jev_ask` returns `None` → no charts → existing assertions unaffected. The `sectors_list_subsectors` tool has no registered views so JEV isn't even invoked.

- [ ] **Step 5: Commit (after user review)**

```bash
git add backend/app/agent/state.py backend/app/agent/tools_node.py backend/app/agent/graph.py backend/tests/test_agent_tools_node.py
git commit -m "phase 11e: tools node judges tool results, charts state field"
```

---

### Task 6: Service — `chart` SSE events + history attachment

**Files:**
- Modify: `backend/app/agent/service.py` (`run_turn` updates handler, `get_thread_messages`)
- Test: `backend/tests/test_chat_api.py` (or new `test_charts_history` block in `test_charts.py` — needs a mocked graph state; check what `test_chat_api.py` already mocks for `get_thread_messages` first)

**Interfaces:**
- Consumes: `state["charts"]` specs with `anchor`
- Produces: `chart` SSE event payloads (spec minus `anchor`); `{role, content, charts}` message dicts from `get_thread_messages`

- [ ] **Step 1: Write the failing test** — append to `test_charts.py` (unit-level, no API needed; `get_thread_messages` uses `get_graph().aget_state` so mock `service.get_graph`):

```python
async def test_history_attaches_charts_to_closing_assistant(monkeypatch):
    from app.agent import service

    values = {
        "messages": [
            HumanMessage(content="harga BBCA"),
            AIMessage(content="", tool_calls=[{"name": "sectors_daily_prices",
                                               "args": {}, "id": "c",
                                               "type": "tool_call"}]),
            ToolMessage(content="{}", tool_call_id="c",
                        name="sectors_daily_prices"),
            AIMessage(content="BBCA ditutup 6.300 (+2%)."),
        ],
        "charts": [
            {"id": "c1", "view": "price_volume", "kind": "price_volume",
             "title": "BBCA daily close", "x": {}, "series": [], "data": [],
             "fetched_at": "f", "format": "number", "anchor": 2},
        ],
    }
    fake_graph = SimpleNamespace(
        aget_state=AsyncMock(
            return_value=SimpleNamespace(values=values)
        )
    )
    monkeypatch.setattr(service, "_graph", fake_graph)

    out = await service.get_thread_messages("tid")
    assert out[1]["role"] == "assistant"
    assert out[1]["charts"][0]["id"] == "c1"
    assert "anchor" not in out[1]["charts"][0]
    assert out[0]["role"] == "user" and "charts" not in out[0]
```

(Imports needed at top of test_charts.py: `from unittest.mock import AsyncMock`, `from langchain_core.messages import AIMessage, HumanMessage, ToolMessage`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend python -m pytest tests/test_charts.py::test_history_attaches_charts_to_closing_assistant -v`
Expected: FAIL — `KeyError: 'charts'` (or `IndexError` — charts not attached yet)

- [ ] **Step 3: Implement**

In `service.run_turn`, inside the `elif kind == "updates":` block, emit chart events from the tools-node update (strip `anchor` — backend-internal):

```python
                elif kind == "updates":
                    for node_name, update in payload.items():
                        if not isinstance(update, dict):
                            continue
                        if node_name == "tools":
                            for spec in update.get("charts") or []:
                                run.emit(
                                    "chart",
                                    {k: v for k, v in spec.items()
                                     if k != "anchor"},
                                )
                        for m in update.get("messages", []):
                            # ... existing agent/tools message handling unchanged
```

In `service.get_thread_messages`, attach charts by anchor:

```python
async def get_thread_messages(thread_id: str | uuid.UUID) -> list[dict]:
    """Serialize the checkpointed message history for the API."""
    config = {"configurable": {"thread_id": str(thread_id)}}
    state = await get_graph().aget_state(config)
    values = state.values if state else {}
    entries: list[tuple[int, dict]] = []
    for i, m in enumerate(values.get("messages", [])):
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        else:
            continue
        if isinstance(m.content, str):
            entries.append((i, {"role": role, "content": m.content}))
    # Each chart belongs to the assistant answer that closed its turn — the
    # first assistant message after the ToolMessage it was produced from.
    for spec in values.get("charts", []):
        anchor = spec.get("anchor", -1)
        target = next(
            (e for i, e in entries
             if i > anchor and e["role"] == "assistant"),
            None,
        )
        if target is not None:
            target.setdefault("charts", []).append(
                {k: v for k, v in spec.items() if k != "anchor"}
            )
    return [e for _, e in entries]
```

- [ ] **Step 4: Run tests**

Run: `docker compose exec backend python -m pytest tests/test_charts.py tests/test_chat_api.py -v`
Expected: all pass

- [ ] **Step 5: Commit (after user review)**

```bash
git add backend/app/agent/service.py backend/tests/test_charts.py
git commit -m "phase 11f: chart sse events + history attachment"
```

---

### Task 7: Frontend plumbing — types, SSE event, store

**Files:**
- Create: `frontend/lib/charts.ts`
- Modify: `frontend/lib/api.ts` (StreamEvent union, ChatMessage)
- Modify: `frontend/lib/stores/chat.ts` (chart event case, toMessages)
- Modify: `frontend/components/chat-messages.tsx` (Message.charts field)
- Deps: `frontend/package.json` (+recharts)

**Interfaces:**
- Consumes: `chart` SSE events (spec minus `anchor`), `charts` on history messages
- Produces: `ChartSpec` type, `formatChartValue`, `Message.charts`

- [ ] **Step 1: Install recharts**

Per docker-compose.yml, `/app/node_modules` is container-side — install and rebuild:

```bash
docker compose exec frontend npm install recharts
docker compose up -d --build frontend
```

Verify: `docker compose exec frontend node -e "console.log(require('recharts/package.json').version)"` — expect 3.x. If npm resolved a version published <7 days ago, pin the previous minor (`npm install recharts@<older>`).

- [ ] **Step 2: Create `frontend/lib/charts.ts`**

```ts
/* Chart spec shared by the SSE stream, history payloads, and components.
   Shape is produced by backend/app/sectors/charts.py — keep in sync. */

export type ChartKind =
  | "line"
  | "area"
  | "signed_area"
  | "bar"
  | "diverging_bar"
  | "grouped_bar"
  | "price_volume";

export type ChartRow = Record<string, string | number | null>;

export type ChartSpec = {
  id: string;
  tool: string;
  view: string;
  kind: ChartKind;
  title: string;
  x: { key: string; label: string; type: "time" | "category" };
  series: { key: string; label: string }[];
  data: ChartRow[];
  fetched_at: string;
  format?: "percent" | "percent_raw" | "idr" | "number";
};

export function formatChartValue(
  v: number | null | undefined,
  format?: ChartSpec["format"],
): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  switch (format) {
    case "percent":
      return `${(v * 100).toFixed(1)}%`;
    case "percent_raw":
      return `${v.toFixed(1)}%`;
    case "idr":
    case "number":
    default: {
      const abs = Math.abs(v);
      if (abs >= 1e12) return `${(v / 1e12).toFixed(1)}T`;
      if (abs >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
      if (abs >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
      if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
      return `${v}`;
    }
  }
}
```

- [ ] **Step 3: `frontend/lib/api.ts` changes**

```ts
import type { ChartSpec } from "@/lib/charts";

export type ChatMessage = {
  role: string;
  content: string;
  charts?: ChartSpec[];
};

export type StreamEvent = {
  seq: number;
  type: "started" | "token" | "tool" | "chart" | "done" | "stopped" | "error";
  data: unknown;
};
```

- [ ] **Step 4: `frontend/components/chat-messages.tsx` — Message type**

Add to the `Message` type:

```ts
import type { ChartSpec } from "@/lib/charts";

export type Message = {
  // ...existing fields
  /** Chart specs emitted by tool results (live + history). */
  charts?: ChartSpec[];
};
```

- [ ] **Step 5: `frontend/lib/stores/chat.ts` changes**

`toMessages` passes charts through:

```ts
function toMessages(
  messages: { role: string; content: string; charts?: ChartSpec[] }[],
): Message[] {
  return messages.map((m, i) => ({
    id: `h-${i}`,
    role: m.role === "user" ? "user" : "assistant",
    content: m.content,
    charts: m.charts,
  }));
}
```

Add the `chart` case in `runStream`'s event switch (after the `"tool"` case):

```ts
          case "chart":
            patch((m) => ({
              charts: [...(m.charts ?? []), ev.data as ChartSpec],
            }));
            break;
```

(Import `ChartSpec` type: `import type { ChartSpec } from "@/lib/charts";`)

- [ ] **Step 6: Typecheck**

Run: `docker compose exec frontend npx tsc --noEmit`
Expected: clean (ChatMessages doesn't render charts yet — `charts` is an unused-but-valid field; eslint may flag nothing since it's consumed in Task 8)

- [ ] **Step 7: Commit (after user review)**

```bash
git add frontend/lib/charts.ts frontend/lib/api.ts frontend/lib/stores/chat.ts frontend/components/chat-messages.tsx frontend/package.json frontend/package-lock.json
git commit -m "phase 11g: chart spec plumbing — types, sse, store"
```

---

### Task 8: Frontend — chart components + message wiring

**Files:**
- Create: `frontend/components/charts/chart-card.tsx` (shell: title + fetched_at caption + responsive frame)
- Create: `frontend/components/charts/chart-block.tsx` (kind dispatcher + all renderers)
- Modify: `frontend/components/chat-messages.tsx` (render `msg.charts`)

**Interfaces:**
- Consumes: `ChartSpec`, `formatChartValue` from `lib/charts.ts`
- Produces: `<ChartBlock spec={spec} />` used by `AssistantMessage`

Design rules: dark-first — `stroke`/`fill` use `var(--primary)` (lavender), `var(--muted-foreground)` for axes/grid text, `var(--border)` for gridlines, tooltip styled like `bg-popover text-popover-foreground border`. Positive/negative values use `var(--primary)` / `var(--destructive)` — never yellow.

- [ ] **Step 1: Create `chart-card.tsx`**

```tsx
"use client";

import type { ReactNode } from "react";

/** Shared frame: title + data-freshness caption + chart area. */
export function ChartCard({
  title,
  fetchedAt,
  children,
}: {
  title: string;
  fetchedAt?: string;
  children: ReactNode;
}) {
  const stamp = fetchedAt
    ? new Date(fetchedAt).toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;
  return (
    <figure className="rounded-xl border border-border bg-card/50 p-4">
      <figcaption className="mb-3 flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-foreground">{title}</span>
        {stamp && (
          <span className="shrink-0 text-[11px] text-ink-tertiary">
            data {stamp}
          </span>
        )}
      </figcaption>
      <div className="h-56 w-full">{children}</div>
    </figure>
  );
}
```

- [ ] **Step 2: Create `chart-block.tsx` — dispatcher + kind renderers**

```tsx
"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartCard } from "@/components/charts/chart-card";
import { formatChartValue, type ChartRow, type ChartSpec } from "@/lib/charts";

const AXIS = { stroke: "var(--muted-foreground)", fontSize: 11, tickLine: false, axisLine: false } as const;
const GRID = { stroke: "var(--border)", strokeDasharray: "3 3", vertical: false } as const;
const TIP = {
  contentStyle: {
    background: "var(--popover)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-sm)",
    fontSize: 12,
    color: "var(--popover-foreground)",
  },
  labelStyle: { color: "var(--muted-foreground)" },
} as const;

const SERIES_COLORS = [
  "var(--primary)",
  "#8b93e8",
  "#a7b0f2",
  "#6ee7d8",
  "#f2a0c0",
];

function fmtValue(spec: ChartSpec) {
  return (v: unknown) => formatChartValue(v as number, spec.format);
}

function Frame({ spec, children }: { spec: ChartSpec; children: React.ReactNode }) {
  return (
    <ChartCard title={spec.title} fetchedAt={spec.fetched_at}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </ChartCard>
  );
}

function SeriesChart({ spec, variant }: { spec: ChartSpec; variant: "line" | "area" }) {
  const Chart = variant === "area" ? AreaChart : LineChart;
  const Series = variant === "area" ? Area : Line;
  return (
    <Frame spec={spec}>
      <Chart data={spec.data} margin={{ left: 8, right: 8, top: 4, bottom: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey={spec.x.key} {...AXIS} />
        <YAxis tickFormatter={fmtValue(spec)} width={56} {...AXIS} />
        <Tooltip formatter={fmtValue(spec)} {...TIP} />
        {spec.series.map((s, i) => (
          <Series
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
            fill={SERIES_COLORS[i % SERIES_COLORS.length]}
            fillOpacity={variant === "area" ? 0.15 : 0}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        ))}
      </Chart>
    </Frame>
  );
}

function SignedArea({ spec }: { spec: ChartSpec }) {
  // Split gradient at y=0 — positive flow lavender, negative destructive.
  const s = spec.series[0];
  const vals = spec.data.map((r) => Number(r[s.key] ?? 0));
  const max = Math.max(...vals, 0);
  const min = Math.min(...vals, 0);
  const off = max === min ? 1 : max / (max - min);
  const gradId = `split-${spec.id}`;
  return (
    <Frame spec={spec}>
      <AreaChart data={spec.data} margin={{ left: 8, right: 8, top: 4, bottom: 0 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset={off} stopColor="var(--primary)" stopOpacity={0.4} />
            <stop offset={off} stopColor="var(--destructive)" stopOpacity={0.4} />
          </linearGradient>
        </defs>
        <CartesianGrid {...GRID} />
        <XAxis dataKey={spec.x.key} {...AXIS} />
        <YAxis tickFormatter={fmtValue(spec)} width={56} {...AXIS} />
        <Tooltip formatter={fmtValue(spec)} {...TIP} />
        <ReferenceLine y={0} stroke="var(--border)" />
        <Area
          type="monotone"
          dataKey={s.key}
          name={s.label}
          stroke="var(--primary)"
          strokeWidth={2}
          fill={`url(#${gradId})`}
          dot={false}
          connectNulls
        />
      </AreaChart>
    </Frame>
  );
}

function Bars({ spec }: { spec: ChartSpec }) {
  return (
    <Frame spec={spec}>
      <BarChart data={spec.data} margin={{ left: 8, right: 8, top: 4, bottom: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey={spec.x.key} {...AXIS} />
        <YAxis tickFormatter={fmtValue(spec)} width={56} {...AXIS} />
        <Tooltip formatter={fmtValue(spec)} {...TIP} />
        {spec.series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            fill={SERIES_COLORS[i % SERIES_COLORS.length]}
            radius={[4, 4, 0, 0]}
          />
        ))}
      </BarChart>
    </Frame>
  );
}

function DivergingBars({ spec }: { spec: ChartSpec }) {
  const s = spec.series[0];
  const hasGroups = spec.data.some((r) => r.group);
  const groups = hasGroups
    ? [...new Set(spec.data.map((r) => String(r.group ?? "")))]
    : [""];
  return (
    <Frame spec={spec}>
      <div className="flex h-full flex-col gap-3 overflow-y-auto">
        {groups.map((g) => {
          const rows = spec.data.filter((r) => String(r.group ?? "") === g);
          return (
            <div key={g || "all"} className="flex min-h-0 flex-1 flex-col">
              {g && (
                <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-ink-tertiary">
                  {g}
                </div>
              )}
              <div className="min-h-0 flex-1">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 24, top: 0, bottom: 0 }}>
                    <CartesianGrid {...GRID} vertical={true} horizontal={false} />
                    <XAxis type="number" tickFormatter={fmtValue(spec)} {...AXIS} />
                    <YAxis type="category" dataKey={spec.x.key} width={56} {...AXIS} />
                    <Tooltip formatter={fmtValue(spec)} {...TIP} />
                    <ReferenceLine x={0} stroke="var(--border)" />
                    <Bar dataKey={s.key} name={s.label} radius={[0, 4, 4, 0]}>
                      {rows.map((r, i) => (
                        <Cell
                          key={i}
                          fill={
                            Number(r[s.key] ?? 0) >= 0
                              ? "var(--primary)"
                              : "var(--destructive)"
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          );
        })}
      </div>
    </Frame>
  );
}

function PriceVolume({ spec }: { spec: ChartSpec }) {
  const [price, volume] = spec.series;
  return (
    <Frame spec={spec}>
      <ComposedChart data={spec.data} margin={{ left: 8, right: 8, top: 4, bottom: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey={spec.x.key} {...AXIS} />
        <YAxis yAxisId="price" tickFormatter={fmtValue(spec)} width={56} {...AXIS} />
        <YAxis
          yAxisId="vol"
          orientation="right"
          tickFormatter={(v) => formatChartValue(v as number, "number")}
          width={48}
          {...AXIS}
        />
        <Tooltip formatter={fmtValue(spec)} {...TIP} />
        {volume && (
          <Bar
            yAxisId="vol"
            dataKey={volume.key}
            name={volume.label}
            fill="var(--muted-foreground)"
            fillOpacity={0.25}
          />
        )}
        <Line
          yAxisId="price"
          type="monotone"
          dataKey={price.key}
          name={price.label}
          stroke="var(--primary)"
          strokeWidth={2}
          dot={false}
          connectNulls
        />
      </ComposedChart>
    </Frame>
  );
}

export function ChartBlock({ spec }: { spec: ChartSpec }) {
  if (!spec?.data?.length) return null;
  switch (spec.kind) {
    case "area":
      return <SeriesChart spec={spec} variant="area" />;
    case "signed_area":
      return <SignedArea spec={spec} />;
    case "bar":
      return <Bars spec={spec} />;
    case "diverging_bar":
      return <DivergingBars spec={spec} />;
    case "grouped_bar":
      return <Bars spec={spec} />;
    case "price_volume":
      return <PriceVolume spec={spec} />;
    case "line":
    default:
      return <SeriesChart spec={spec} variant="line" />;
  }
}
```

Notes for the implementer:
- `Brush` zoom: add inside `SeriesChart`/`SignedArea`/`PriceVolume` when `spec.x.type === "time" && spec.data.length > 15`:
  ```tsx
  {spec.x.type === "time" && spec.data.length > 15 && (
    <Brush dataKey={spec.x.key} height={18} stroke="var(--primary)"
           travellerWidth={8} />
  )}
  ```
  (import `Brush` from recharts; keep margin bottom ≥ 4).
- `grouped_bar` renders one `Bar` per series entry — already handled by `Bars` mapping `spec.series`.

- [ ] **Step 3: Wire into `AssistantMessage` in `chat-messages.tsx`**

```tsx
import { ChartBlock } from "@/components/charts/chart-block";

// inside AssistantMessage, after the markdown block:
      {msg.charts?.map((c) => (
        <ChartBlock key={c.id} spec={c} />
      ))}
```

Place it inside the `min-w-0` wrapper after the markdown div; add `mt-3` spacing via a wrapping div: `<div className="mt-3 flex flex-col gap-3">`.

- [ ] **Step 4: Frontend checks**

```bash
docker compose exec frontend npx tsc --noEmit
docker compose exec frontend npx eslint .
docker compose exec frontend npm run build
```

Expected: clean. Fix any recharts/TS API mismatches (recharts 3.x prop types are strict — e.g. `vertical` on `CartesianGrid`, `travellerWidth` on `Brush`).

- [ ] **Step 5: Manual verification**

`docker compose up -d` (all three services), open `http://localhost:3000`, ask "harga BBCA sebulan terakhir" — expect: tool status line → answer text → close-price+volume chart card. Reopen the thread — chart persists via checkpoint. Ask "top gainers hari ini" — diverging bar chart. Check browser console for errors.

- [ ] **Step 6: `/code-simplifier` audit + commit (after user review)**

```bash
git add frontend/components/charts/ frontend/components/chat-messages.tsx
git commit -m "phase 11h: chart components — kind renderers + message wiring"
```

---

## Self-review notes

- **Spec coverage:** registry (T1–T4) ✓, state+node (T5) ✓, stream+history (T6) ✓, types+store (T7) ✓, components (T8) ✓, JEV gate (T1) ✓, persistence via checkpointer (T5+T6) ✓, all-feasible-tools scope ✓, recharts ✓.
- **Anchor invariant:** `messages` is append-only (state.py docstring) — anchors stay valid. If a `charts` spec's anchor finds no later assistant message (run stopped before any text), the chart is silently dropped from history — acceptable.
- **`_post_turn`/`_ensure_title`** untouched — they don't read `charts`.
- **Detached runs:** `chart` events live in the same replay buffer as tokens — reattach path (`GET /threads/{id}/stream`) replays them automatically.
- **JEV latency:** one call per chartable tool result inside `tools` node; `news`/`filings`/`suspensions`/`corporate_actions`/`list_subsectors` have no views → zero JEV spend.
- **`test_agent_graph.py` compatibility:** real `tools` node runs in Task 5 tests; `sectors_list_subsectors` has no views → judge returns `None` before JEV; other tests mock `agent_llm` only.
