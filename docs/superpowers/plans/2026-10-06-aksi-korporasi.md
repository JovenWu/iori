# Aksi Korporasi Copilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A page (`/action`) where a user enters the IDX stocks they hold, presses "Cek aksi korporasi", and an agent finds the corporate actions affecting those holdings (rights issues, dividends, warrants), computes the personal impact deterministically, gathers sourced context from Sectors data, and writes a gated bilingual brief per event — streamed live and saved as a report. Includes a labelled historical replay mode.

**Architecture:** New backend package `app/aksi/` with a dedicated LangGraph (`scan → context → investigate → compute → brief → persist`, looping per event) run as a detached job on the existing run registry and streamed over SSE (same envelope as chat). Pure calculators produce every number; the LLM may only write placeholders, and a deterministic + JEV gate rejects digits or advice language (template fallback). Raw Sectors reads go through the existing permanent cache with the same keys as the chat tools. The frontend adds a route inside the `(chat)` layout, a sidebar item, a zustand store and event-card components that reuse the Spark `AgentStatus`.

**Tech Stack:** Python 3.10 (container) / FastAPI / LangGraph / SQLAlchemy async + Alembic / typesafe-sdk JEV (`app.core.jev`) / pytest; Next.js 16.3.5 + React 19.2 + Tailwind v4 + shadcn (radix-ui) + zustand 5 + sonner + lucide-react.

**Spec:** `docs/superpowers/specs/2026-10-06-aksi-korporasi-design.md` (problem, evidence, UX, formulas, risks). Where the spec and this plan differ on names or signatures, **this plan wins**.

## Global Constraints

- **Deadline:** submission closes Thu 8 Oct 2026 23:59 WIB and the repo freezes on submission. Protect Thursday afternoon for video recording.
- **Commit gate:** the user reviews before EVERY commit — pause and ask, never commit unreviewed work (team convention; the user may relax it).
- Commit style: lowercase `phase 14<x>: short description` (sub-phases 14a, 14b, …). **No** `Co-Authored-By` / `Generated with` trailers — commits are authored by the user only. Never commit `.env` or secrets.
- Backend tests: `docker compose exec backend python -m pytest tests` (single file: `... python -m pytest tests/test_aksi_calc.py -v`).
- Frontend checks: `docker compose exec frontend npx tsc --noEmit`, `docker compose exec frontend npx eslint .`, `docker compose exec frontend npm run build`.
- Migrations: the backend container runs `alembic upgrade head` on start; after adding a migration run `docker compose exec backend alembic upgrade head` then `docker compose exec backend alembic check` (must report no new operations).
- Next.js 16 has breaking changes — before touching Next-specific APIs (routing, layouts, `next/navigation`) read `frontend/node_modules/next/dist/docs/`. The new page is a plain client component mirroring `app/(chat)/page.tsx`.
- Design (DESIGN.md / PRODUCT.md): dark canvas, lavender `var(--primary)` only for the primary action, focus and the "today" marker; danger `var(--destructive)` for deadlines ≤ 2 days; **no yellow/bright accents**; hairline borders (`border-border`), cards `bg-card` with 12px radius (`rounded-xl`); numbers, tickers and tool names in `font-mono`.
- **No advice, ever (POJK 6/2026):** no output may tell the user to buy, sell, hold, exercise or not exercise. UI copy uses neutral scenarios; every card shows "Informasi edukatif, bukan rekomendasi investasi."
- **Numbers only from code:** every figure comes from `app/aksi/calc.py`; the LLM never writes digits (enforced by `app/aksi/gate.py`).
- **Credits:** the team has < 1,000 Sectors credits. Never pass `refresh=True` from aksi code; per-run budget default 25; tests always mock upstream (`app.sectors.client.get`).
- JEV fallback contract: `jev_ask` returns `None` when unconfigured/failed — every call site degrades gracefully (see `app/core/jev.py`).
- After code changes, run the `/code-simplifier` audit before finishing a task (project rule).
- The backend container runs **Python 3.10** — no 3.11+ syntax (`StrEnum`, `except*`, `typing.Self`).

## Shared contracts (all tasks)

```python
# Event — produced by app.aksi.events.normalize, internal to the backend
{
    "id": "WIFI:right_issue:2025-07-02",   # f"{symbol}:{kind}:{key_date}"
    "symbol": "WIFI",
    "kind": "right_issue" | "dividend" | "warrant",
    "row": {...},                          # the raw Sectors calendar row
    "phase": "before_cum" | "awaiting_window" | "window_open" | "awaiting_payment" | "before_window",
    "shares": 1000,
    "avg_price": float | None,
    "urgency": int | None,                 # calendar days to the next deadline
}

# PublicEvent — app.aksi.events.public(ev); SSE `event_found` data and report `event`
{"event_id", "symbol", "kind", "phase", "shares", "urgency", "row"}

# Figure — app.aksi.calc.Figure.to_json()
{"key": str, "value": int | float | str | None, "unit": "IDR"|"shares"|"rights"|"ratio"|"days"|"date",
 "formula": str, "inputs": dict, "gap": str | None}

# Finding — app.aksi.findings
{"id": str, "kind": str, "text_id": str, "text_en": str, "values": dict,
 "source_tool": str, "fetched_at": str | None}

# Brief — app.aksi.briefs.produce()
{"headline_id", "headline_en", "summary_id", "summary_en",
 "verify_id": [str], "verify_en": [str], "context_ids": [str],
 "gate": {"passed": bool, "reasons": [str], "template": bool}}

# Report event (persisted in aksi_reports.events, returned by /aksi/reports/*)
{"event": PublicEvent, "figures": {key: Figure}, "findings": [Finding], "brief": Brief}
```

SSE (`data: {"seq": n, "type": ..., "data": ...}`), emitted in this order per run:
`started {report_id, mode, as_of, started_at}` → per node `step {node, event_id?}` → `tool {name, args, status:"call"}` / `tool {name, status:"done"}` → `event_found PublicEvent` → `numbers {event_id, figures}` → `finding {event_id, ...Finding}` → `brief {event_id, ...Brief}` → `budget {credits_used, budget}` → terminal `done {report_id, events, credits_spent}` | `stopped {report_id}` | `error "<message>"`.

## Verified upstream shapes (docs.sectors.app — do not guess)

- Calendar `GET /v2/corporate-actions/?start&end&type=a,b` → `{start, end, <type>: [rows]}` (only requested types). Window clamped to 90 days ending at `end`; `end` may be future; 1 credit per type.
  - `right_issue`: `symbol` ("WIFI.JK"), `ex_date`, `cum_date`, `recording_date`, `trading_period_start`, `trading_period_end`, `subscription_date`, `price`, `old_ratio`, `new_ratio`. **Verified:** old 4 / new 5 = "every 4 old shares receive 5 HMETD"; the deadline is `trading_period_end`.
  - `dividend`: `symbol`, `ex_date`, `cum_date`, `recording_date`, `payment_date`, `dividend_amount`, `dividend_yield`. `upcoming_dividend`: same without `dividend_yield`.
  - `warrant`: `symbol`, `trading_period_start`, `trading_period_end`, `ex_per_start`, `ex_per_end`, `maturity_date`, `price`, `ratio_warrant`, `ratio_shares`.
- Daily `GET /v2/daily/{symbol}/?start&end` → `[{symbol, date, close, open, high, low, volume, market_cap}]` (≤ 90 days, end ≤ today).
- Filings `GET /v2/filings/?symbol&start&end&limit` → paginated; rows carry `timestamp`, `holder_name`, `holder_type`, `transaction_type` ("buy"/"sell"), `amount_transaction`, `price`, `share_percentage_before`, `share_percentage_after`. Read rows defensively (`data` list, or `data.results`). Future `end` → 400.
- Shareholders `GET /v2/company/shareholders-composition/{symbol}/?year` → `{symbol, year, data: [{date, shares_number, total_l, total_f, <category>_l, <category>_f}]}`.
- Company report `GET /v2/company/report/{symbol}/?sections=ownership` → `{symbol, ownership: {...}}`. Exact ownership keys are confirmed in Task 0. `findings.top_holder` scans any nested list item with `name` + `share_percentage`/`percentage`.

## Workstreams (parallel agents)

| Agent | Tasks | Notes |
|---|---|---|
| **Backend** | 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 | Task 0 first (go/no-go). Task 2 lands the holdings API early so the frontend can integrate |
| **Frontend** | 9 → 10 → 11 | Starts immediately against the contracts above. Uses the sample report in Appendix A for UI work until Task 7 lands (temporary, never committed) |
| **Either (last)** | 12 | Integration, demo prep, README |

Agents must not edit each other's files. The only shared file is `frontend/lib/tool-labels.ts` (Task 9 owns it).

---

### Task 0: Data check (go/no-go, warms the cache)

**Files:**
- Create: `backend/scripts/__init__.py` (empty)
- Create: `backend/scripts/aksi_data_check.py`

**Interfaces:**
- Consumes: `app.sectors.cache.cached_get`, `app.sectors.client.init_client/close_client`, `app.sectors.freshness.Freshness/WIB`.
- Produces: cached upstream responses (shared with the feature's exact cache keys) and a written go/no-go note for the user.

- [ ] **Step 1: Write the script**

```python
# backend/scripts/aksi_data_check.py
"""One-off data check for the Aksi Korporasi feature (~13 credits cold).

Requests exactly what the feature requests for the live scan and the WIFI
replay (same paths + params → same cache keys), so the demo later replays from
the permanent cache for free. Prints a compact report.

Run: docker compose exec backend python -m scripts.aksi_data_check
"""

import asyncio
import json
from datetime import date, datetime, timedelta

from app.sectors import cache, client
from app.sectors.freshness import WIB, Freshness

KINDS = "dividend,right_issue,upcoming_dividend,warrant"  # sorted, as the feature sends them
REPLAY_AS_OF = date(2025, 7, 10)


def _window(as_of: date) -> dict:
    return {
        "start": (as_of - timedelta(days=30)).isoformat(),
        "end": (as_of + timedelta(days=60)).isoformat(),
        "type": KINDS,
    }


CHECKS = [
    ("calendar_live", "corporate_actions", "/v2/corporate-actions/",
     _window(datetime.now(WIB).date()), Freshness.EOD, 4),
    ("calendar_replay", "corporate_actions", "/v2/corporate-actions/",
     _window(REPLAY_AS_OF), Freshness.EOD, 4),
    ("wifi_actions", "company_corporate_actions",
     "/v2/company/corporate-actions/WIFI/", {}, Freshness.EOD, 1),
    ("wifi_prices", "daily", "/v2/daily/WIFI/",
     {"start": (REPLAY_AS_OF - timedelta(days=89)).isoformat(),
      "end": REPLAY_AS_OF.isoformat()}, Freshness.EOD, 1),
    ("wifi_filings", "filings", "/v2/filings/",
     {"limit": 30, "symbol": "WIFI",
      "start": (REPLAY_AS_OF - timedelta(days=45)).isoformat(),
      "end": REPLAY_AS_OF.isoformat()}, Freshness.NEWS, 1),
    ("wifi_shareholders", "shareholders",
     "/v2/company/shareholders-composition/WIFI/", {"year": 2025},
     Freshness.HISTORICAL, 1),
    ("wifi_ownership", "company_report", "/v2/company/report/WIFI/",
     {"sections": "ownership"}, Freshness.EOD, 1),
]


def _describe(data) -> str:
    if isinstance(data, list):
        return f"{len(data)} rows"
    if isinstance(data, dict):
        return ", ".join(
            f"{k}:{len(v)}" if isinstance(v, list) else k for k, v in data.items()
        )
    return type(data).__name__


async def main() -> None:
    client.init_client()
    try:
        for label, endpoint, path, params, freshness, credits in CHECKS:
            res = await cache.cached_get(
                endpoint, path, params, freshness, credits=credits
            )
            print(f"\n== {label}: status={res.status} source={res.source} "
                  f"{_describe(res.data)}")
            if label.startswith("calendar") and isinstance(res.data, dict):
                for kind in ("right_issue", "warrant"):
                    for row in res.data.get(kind) or []:
                        print(f"   {kind}: {json.dumps(row, default=str)}")
            else:
                print("   " + json.dumps(res.data, default=str)[:1500])
    finally:
        await client.close_client()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it**

Run: `docker compose exec backend python -m scripts.aksi_data_check`
Expected: 7 sections, each `status=200`. `calendar_replay` lists the WIFI `right_issue` row (old_ratio 4, new_ratio 5, price 2000).

- [ ] **Step 3: Report go/no-go to the user (no commit yet)**

Write a short note in your reply (not a file) covering:
- **Go** if `wifi_actions` or `calendar_replay` contains the WIFI rights issue **and** `wifi_prices` has a close on/before 2025-07-01 **and** `calendar_live` has at least one row of any type.
- The live symbols found (they become demo holdings).
- The exact ownership keys in `wifi_ownership`. If the top-holder list is not items with `name` + `share_percentage`, adapt `findings.top_holder` in Task 4 accordingly.
- Whether `wifi_filings` contains an ISB (PT Investasi Sukses Bersama) filing. If one dated ≤ 2025-07-15 exists, the replay demo date may move to that day.
- Stop and ask the user if any **Go** condition fails.

- [ ] **Step 4: Commit (after user review)**

```bash
git add backend/scripts/__init__.py backend/scripts/aksi_data_check.py
git commit -m "phase 14a: aksi data check script"
```

---

### Task 1: Calculators (`app/aksi/calc.py`)

**Files:**
- Create: `backend/app/aksi/__init__.py` (empty)
- Create: `backend/app/aksi/calc.py`
- Test: `backend/tests/test_aksi_calc.py`

**Interfaces:**
- Produces:
  - `Figure` dataclass with `.to_json() -> dict`
  - `parse_decimal(v) -> Decimal | None`, `parse_date(v) -> date | None`, `jsonable(v)`
  - `close_on_or_before(price_rows: list[dict], day: str) -> tuple[Decimal | None, str | None]`
  - `phase(kind: str, row: dict, today: date) -> str`
  - `rights_issue(shares: int, row: dict, p_cum, p_now, today: date) -> dict[str, Figure]`
  - `dividend(shares: int, row: dict, today: date, avg_price=None) -> dict[str, Figure]`
  - `warrant(shares: int, row: dict, p_now, today: date) -> dict[str, Figure]`
  - `figures_for(ev: dict, price_rows: list[dict], today: date) -> dict[str, dict]` (JSON-ready)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_aksi_calc.py
"""Deterministic calculators — the WIFI 2025 rights issue is the oracle."""

from datetime import date
from decimal import Decimal

from app.aksi import calc

WIFI = {
    "symbol": "WIFI.JK", "ex_date": "2025-07-02", "cum_date": "2025-07-01",
    "recording_date": "2025-07-03", "trading_period_start": "2025-07-07",
    "trading_period_end": "2025-07-15", "subscription_date": "2025-07-03",
    "price": 2000, "old_ratio": 4, "new_ratio": 5,
}


def test_rights_issue_wifi_oracle():
    f = calc.rights_issue(1000, WIFI, 3000, 2310, date(2025, 7, 10))
    assert f["rights_entitled"].value == 1250
    assert f["cost_to_exercise_all"].value == Decimal(2_500_000)
    assert abs(f["terp"].value - Decimal("2444.4444")) < Decimal("0.001")
    assert abs(f["rights_value_total"].value - Decimal("555555.56")) < Decimal("0.01")
    assert abs(f["dilution_if_ignored"].value - Decimal("0.5556")) < Decimal("0.0001")
    assert f["deadline"].value == date(2025, 7, 15)
    assert f["days_to_deadline"].value == 5


def test_rights_issue_value_identities():
    f = calc.rights_issue(1000, WIFI, 3000, None, date(2025, 6, 30))
    exercised = f["value_if_exercised"].value
    assert abs(exercised - (Decimal(3_000_000) + f["cost_to_exercise_all"].value)) < Decimal("0.01")
    kept = f["value_if_ignored"].value + f["rights_value_total"].value
    assert abs(kept - Decimal(3_000_000)) < Decimal("0.01")


def test_fractional_rights_are_floored():
    f = calc.rights_issue(1001, WIFI, 3000, None, date(2025, 6, 30))
    assert f["rights_entitled"].value == 1251  # 1001 × 5/4 = 1251.25


def test_missing_price_yields_gaps_not_numbers():
    f = calc.rights_issue(1000, {**WIFI, "price": None}, 3000, None, date(2025, 6, 30))
    assert f["rights_entitled"].value == 1250
    assert f["cost_to_exercise_all"].value is None and f["cost_to_exercise_all"].gap
    assert f["terp"].value is None


def test_right_value_never_negative():
    f = calc.rights_issue(1000, WIFI, 1500, None, date(2025, 6, 30))
    assert f["right_value"].value == 0
    assert f["rights_value_total"].value == 0


def test_dividend_gross_and_days_to_cum():
    row = {"symbol": "BBMD.JK", "ex_date": "2025-07-01", "cum_date": "2025-06-30",
           "recording_date": "2025-07-02", "payment_date": "2025-07-18",
           "dividend_amount": 34.25}
    f = calc.dividend(5000, row, date(2025, 6, 27), avg_price=1900)
    assert f["gross_dividend"].value == Decimal("171250")
    assert f["days_to_cum"].value == 3
    assert abs(f["yield_on_cost"].value - Decimal("0.018026")) < Decimal("0.00001")


def test_warrant_intrinsic_and_deadline():
    row = {"symbol": "ABCD.JK", "trading_period_start": "2025-01-10",
           "ex_per_start": "2025-07-01", "ex_per_end": "2026-01-09",
           "maturity_date": "2026-01-09", "price": 150,
           "ratio_warrant": 1, "ratio_shares": 5}
    f = calc.warrant(1000, row, 180, date(2025, 12, 1))
    assert f["intrinsic_per_warrant"].value == 30
    assert f["days_to_deadline"].value == 39


def test_phase_right_issue():
    assert calc.phase("right_issue", WIFI, date(2025, 6, 30)) == "before_cum"
    assert calc.phase("right_issue", WIFI, date(2025, 7, 3)) == "awaiting_window"
    assert calc.phase("right_issue", WIFI, date(2025, 7, 10)) == "window_open"
    assert calc.phase("right_issue", WIFI, date(2025, 7, 16)) == "expired"


def test_close_lookup_and_figures_for():
    prices = [{"date": "2025-06-30", "close": 2950},
              {"date": "2025-07-01", "close": 3000},
              {"date": "2025-07-09", "close": 2310}]
    assert calc.close_on_or_before(prices, "2025-07-05") == (Decimal(3000), "2025-07-01")
    figs = calc.figures_for({"kind": "right_issue", "row": WIFI, "shares": 1000},
                            prices, date(2025, 7, 10))
    assert figs["rights_entitled"]["value"] == 1250
    assert figs["cost_to_exercise_all"]["value"] == 2500000
    assert round(figs["terp"]["value"], 2) == 2444.44
    assert figs["terp"]["inputs"]["p_cum"] == 3000
    assert figs["deadline"]["value"] == "2025-07-15"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend python -m pytest tests/test_aksi_calc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.aksi'`.

- [ ] **Step 3: Implement**

```python
# backend/app/aksi/calc.py
"""Deterministic corporate-action calculators.

Every number the Aksi Korporasi feature shows comes from here — the LLM never
computes or writes figures. Pure functions: no I/O and no clock (callers pass
`today`). Decimal throughout; values are rounded only when formatted.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any

ZERO = Decimal(0)


@dataclass(frozen=True)
class Figure:
    key: str
    value: Any  # Decimal | int | date | None
    unit: str  # IDR | shares | rights | ratio | days | date
    formula: str
    inputs: dict = field(default_factory=dict)
    gap: str | None = None

    def to_json(self) -> dict:
        return {
            "key": self.key,
            "value": jsonable(self.value),
            "unit": self.unit,
            "formula": self.formula,
            "inputs": {k: jsonable(v) for k, v in self.inputs.items()},
            "gap": self.gap,
        }


def jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(round(v, 6))
    if isinstance(v, date):
        return v.isoformat()
    return v


def parse_decimal(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def parse_date(v: Any) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _gap(key: str, unit: str, formula: str, *missing: str) -> Figure:
    return Figure(key, None, unit, formula, gap="missing: " + ", ".join(missing))


def _days(key: str, target: date | None, today: date, formula: str) -> Figure:
    if target is None:
        return _gap(key, "days", formula, "date")
    return Figure(key, (target - today).days, "days", formula,
                  {"today": today, "target": target})


def close_on_or_before(price_rows: list[dict], day: str) -> tuple[Decimal | None, str | None]:
    """Latest close dated on or before `day` (YYYY-MM-DD) → (close, date)."""
    best: tuple[Decimal, str] | None = None
    for r in price_rows:
        d = str(r.get("date") or "")[:10]
        c = parse_decimal(r.get("close"))
        if d and c is not None and d <= day and (best is None or d > best[1]):
            best = (c, d)
    return best if best else (None, None)


def phase(kind: str, row: dict, today: date) -> str:
    if kind == "right_issue":
        cum = parse_date(row.get("cum_date"))
        start = parse_date(row.get("trading_period_start"))
        end = parse_date(row.get("trading_period_end"))
        if end and today > end:
            return "expired"
        if start and end and start <= today <= end:
            return "window_open"
        if cum and today <= cum:
            return "before_cum"
        return "awaiting_window"
    if kind == "dividend":
        cum = parse_date(row.get("cum_date"))
        pay = parse_date(row.get("payment_date"))
        if cum and today <= cum:
            return "before_cum"
        if pay and today <= pay:
            return "awaiting_payment"
        return "paid"
    if kind == "warrant":
        start = parse_date(row.get("ex_per_start"))
        last = parse_date(row.get("ex_per_end")) or parse_date(row.get("maturity_date"))
        if last and today > last:
            return "expired"
        if start and last and start <= today <= last:
            return "window_open"
        return "before_window"
    return "unknown"


def rights_issue(shares: int, row: dict, p_cum: Any, p_now: Any, today: date) -> dict[str, Figure]:
    sh = Decimal(shares)
    old = parse_decimal(row.get("old_ratio"))
    new = parse_decimal(row.get("new_ratio"))
    price = parse_decimal(row.get("price"))
    p_cum = parse_decimal(p_cum)
    p_now = parse_decimal(p_now)
    ratio_ok = old is not None and new is not None and old > 0 and new > 0
    out: dict[str, Figure] = {}

    f = "floor(shares × new_ratio / old_ratio)"
    rights: int | None = None
    if ratio_ok:
        rights = int((sh * new / old).to_integral_value(rounding=ROUND_FLOOR))
        out["rights_entitled"] = Figure("rights_entitled", rights, "rights", f,
                                        {"shares": shares, "new_ratio": new, "old_ratio": old})
    else:
        out["rights_entitled"] = _gap("rights_entitled", "rights", f, "old_ratio", "new_ratio")

    f = "new_ratio / (old_ratio + new_ratio)"
    out["dilution_if_ignored"] = (
        Figure("dilution_if_ignored", new / (old + new), "ratio", f,
               {"new_ratio": new, "old_ratio": old})
        if ratio_ok else _gap("dilution_if_ignored", "ratio", f, "old_ratio", "new_ratio")
    )

    f = "rights_entitled × price"
    out["cost_to_exercise_all"] = (
        Figure("cost_to_exercise_all", Decimal(rights) * price, "IDR", f,
               {"rights_entitled": rights, "price": price})
        if rights is not None and price is not None
        else _gap("cost_to_exercise_all", "IDR", f, "rights_entitled", "price")
    )

    f_terp = "(old_ratio × p_cum + new_ratio × price) / (old_ratio + new_ratio)"
    if ratio_ok and price is not None and p_cum is not None:
        terp = (old * p_cum + new * price) / (old + new)
        rv = max(ZERO, terp - price)
        out["terp"] = Figure("terp", terp, "IDR", f_terp,
                             {"old_ratio": old, "new_ratio": new, "p_cum": p_cum, "price": price})
        out["right_value"] = Figure("right_value", rv, "IDR", "max(0, terp − price)",
                                    {"terp": terp, "price": price})
        if rights is not None:
            out["rights_value_total"] = Figure(
                "rights_value_total", Decimal(rights) * rv, "IDR",
                "rights_entitled × right_value", {"rights_entitled": rights, "right_value": rv})
            out["value_if_ignored"] = Figure(
                "value_if_ignored", sh * terp, "IDR", "shares × terp",
                {"shares": shares, "terp": terp})
            out["value_if_exercised"] = Figure(
                "value_if_exercised", (sh + rights) * terp, "IDR",
                "(shares + rights_entitled) × terp",
                {"shares": shares, "rights_entitled": rights, "terp": terp})
    else:
        out["terp"] = _gap("terp", "IDR", f_terp, "old_ratio/new_ratio/price/p_cum")
        out["rights_value_total"] = _gap("rights_value_total", "IDR",
                                         "rights_entitled × right_value", "terp")

    if p_now is not None and price is not None and p_now > 0:
        out["discount_to_market"] = Figure(
            "discount_to_market", (p_now - price) / p_now, "ratio",
            "(p_now − price) / p_now", {"p_now": p_now, "price": price})

    deadline = parse_date(row.get("trading_period_end"))
    out["deadline"] = (Figure("deadline", deadline, "date", "trading_period_end") if deadline
                       else _gap("deadline", "date", "trading_period_end", "trading_period_end"))
    out["days_to_deadline"] = _days("days_to_deadline", deadline, today,
                                    "deadline − today (calendar days)")
    return out


def dividend(shares: int, row: dict, today: date, avg_price: Any = None) -> dict[str, Figure]:
    amount = parse_decimal(row.get("dividend_amount"))
    avg = parse_decimal(avg_price)
    out: dict[str, Figure] = {}
    f = "shares × dividend_amount"
    out["gross_dividend"] = (
        Figure("gross_dividend", Decimal(shares) * amount, "IDR", f,
               {"shares": shares, "dividend_amount": amount})
        if amount is not None else _gap("gross_dividend", "IDR", f, "dividend_amount")
    )
    out["days_to_cum"] = _days("days_to_cum", parse_date(row.get("cum_date")), today,
                               "cum_date − today (calendar days)")
    if amount is not None and avg is not None and avg > 0:
        out["yield_on_cost"] = Figure("yield_on_cost", amount / avg, "ratio",
                                      "dividend_amount / avg_price",
                                      {"dividend_amount": amount, "avg_price": avg})
    return out


def warrant(shares: int, row: dict, p_now: Any, today: date) -> dict[str, Figure]:
    price = parse_decimal(row.get("price"))
    p_now = parse_decimal(p_now)
    out: dict[str, Figure] = {}
    f = "max(0, p_now − price)"
    out["intrinsic_per_warrant"] = (
        Figure("intrinsic_per_warrant", max(ZERO, p_now - price), "IDR", f,
               {"p_now": p_now, "price": price})
        if price is not None and p_now is not None
        else _gap("intrinsic_per_warrant", "IDR", f, "price", "p_now")
    )
    deadline = parse_date(row.get("ex_per_end")) or parse_date(row.get("maturity_date"))
    f = "ex_per_end or maturity_date"
    out["deadline"] = (Figure("deadline", deadline, "date", f) if deadline
                       else _gap("deadline", "date", f, "ex_per_end", "maturity_date"))
    out["days_to_deadline"] = _days("days_to_deadline", deadline, today,
                                    "deadline − today (calendar days)")
    return out


def figures_for(ev: dict, price_rows: list[dict], today: date) -> dict[str, dict]:
    """All figures for one event, JSON-ready. `price_rows` are daily rows."""
    row, kind, shares = ev["row"], ev["kind"], ev["shares"]
    p_now, _ = close_on_or_before(price_rows, today.isoformat())
    if kind == "right_issue":
        cum = str(row.get("cum_date") or today.isoformat())[:10]
        p_cum, _ = close_on_or_before(price_rows, min(cum, today.isoformat()))
        figs = rights_issue(shares, row, p_cum, p_now, today)
    elif kind == "dividend":
        figs = dividend(shares, row, today, ev.get("avg_price"))
    elif kind == "warrant":
        figs = warrant(shares, row, p_now, today)
    else:
        figs = {}
    return {k: f.to_json() for k, f in figs.items()}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec backend python -m pytest tests/test_aksi_calc.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit (after user review)**

```bash
git add backend/app/aksi/__init__.py backend/app/aksi/calc.py backend/tests/test_aksi_calc.py
git commit -m "phase 14b: aksi calculators"
```

---

### Task 2: Persistence, holdings API, shared SSE helper

**Files:**
- Create: `backend/app/models/holding.py`, `backend/app/models/aksi_report.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/20261006_1200_b4e1a7c9d2f3_holdings_aksi_reports.py`
- Create: `backend/app/schemas/aksi.py`
- Create: `backend/app/aksi/store.py`
- Create: `backend/app/api/sse.py`
- Modify: `backend/app/api/v1/endpoints/chat.py` (use the shared SSE helper)
- Create: `backend/app/api/v1/endpoints/aksi.py` (holdings routes only in this task)
- Modify: `backend/app/api/v1/api.py`
- Test: `backend/tests/test_aksi_holdings_api.py`

**Interfaces:**
- Produces:
  - `store.list_holdings(user_id) -> list[{symbol, shares, avg_price}]` (ordered by symbol)
  - `store.replace_holdings(user_id, holdings: list[dict]) -> None`
  - `store.create_report(user_id, mode, as_of: date, holdings) -> str` (report id)
  - `store.append_event(report_id: str, result: dict, credits: int) -> None`
  - `store.finish_report(report_id: str, status: str, credits: int | None) -> None`
  - `store.latest_report(user_id, mode: str | None) -> dict | None`, `store.get_report(user_id, report_id: str) -> dict | None`
  - `app.api.sse.sse_response(run, last_seq=0) -> StreamingResponse`
  - Schemas: `HoldingIn`, `HoldingsIn`, `HoldingsOut`, `CheckRequest`, `ReportOut`, `ImpactRequest`, `ImpactOut`, `normalize_symbol`
  - Routes: `GET/PUT /api/v1/aksi/holdings`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_aksi_holdings_api.py
"""Holdings CRUD — the scope of a user's corporate-action checks."""

import pytest

from app.core.config import settings

URL = "/api/v1/aksi/holdings"


async def _login(client) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.APP_USERNAME, "password": settings.APP_PASSWORD},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_put_then_get_normalizes_and_sorts(client):
    h = await _login(client)
    resp = await client.put(URL, headers=h, json={"holdings": [
        {"symbol": "wifi.jk", "shares": 1000},
        {"symbol": "BBCA", "shares": 500, "avg_price": 8750},
    ]})
    assert resp.status_code == 200
    got = (await client.get(URL, headers=h)).json()["holdings"]
    assert got == [
        {"symbol": "BBCA", "shares": 500, "avg_price": 8750.0},
        {"symbol": "WIFI", "shares": 1000, "avg_price": None},
    ]


@pytest.mark.asyncio
async def test_put_replaces_previous_holdings(client):
    h = await _login(client)
    await client.put(URL, headers=h, json={"holdings": [
        {"symbol": "BBCA", "shares": 1}, {"symbol": "TLKM", "shares": 2}]})
    await client.put(URL, headers=h, json={"holdings": [{"symbol": "ASII", "shares": 3}]})
    got = (await client.get(URL, headers=h)).json()["holdings"]
    assert [x["symbol"] for x in got] == ["ASII"]


@pytest.mark.asyncio
async def test_invalid_payloads_rejected(client):
    h = await _login(client)
    bad_symbol = await client.put(URL, headers=h, json={"holdings": [{"symbol": "TOOLONG", "shares": 1}]})
    duplicate = await client.put(URL, headers=h, json={"holdings": [
        {"symbol": "BBCA", "shares": 1}, {"symbol": "bbca", "shares": 2}]})
    zero = await client.put(URL, headers=h, json={"holdings": [{"symbol": "BBCA", "shares": 0}]})
    assert [bad_symbol.status_code, duplicate.status_code, zero.status_code] == [422, 422, 422]


@pytest.mark.asyncio
async def test_requires_auth(client):
    assert (await client.get(URL)).status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend python -m pytest tests/test_aksi_holdings_api.py -v`
Expected: FAIL (404 on `/api/v1/aksi/holdings`).

- [ ] **Step 3: Models**

```python
# backend/app/models/holding.py
import uuid
from decimal import Decimal

from sqlalchemy import UUID, BigInteger, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class Holding(TimeStampedBase):
    """A stock the user holds — the scope of their corporate-action checks."""

    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_holdings_user_symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(4), nullable=False)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    avg_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
```

```python
# backend/app/models/aksi_report.py
import uuid
from datetime import date

from sqlalchemy import UUID, Date, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class AksiReport(TimeStampedBase):
    """One corporate-action check. Events are appended as each finishes, so a
    stopped run keeps its partial results."""

    __tablename__ = "aksi_reports"
    __table_args__ = (Index("ix_aksi_reports_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(8), nullable=False)  # live | replay
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # running|done|stopped|error
    holdings_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    events: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    credits_spent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

```python
# backend/app/models/__init__.py
from app.models.aksi_report import AksiReport
from app.models.holding import Holding
from app.models.memory import Memory
from app.models.sectors_cache import SectorsCache
from app.models.thread import Thread
from app.models.thread_digest import ThreadDigest
from app.models.user import User

__all__ = [
    "AksiReport", "Holding", "Memory", "SectorsCache", "Thread", "ThreadDigest", "User",
]
```

- [ ] **Step 4: Migration**

```python
# backend/alembic/versions/20261006_1200_b4e1a7c9d2f3_holdings_aksi_reports.py
"""holdings and aksi_reports

Revision ID: b4e1a7c9d2f3
Revises: d031417a4a27
Create Date: 2026-10-06 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b4e1a7c9d2f3'
down_revision: Union[str, None] = 'd031417a4a27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('holdings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=4), nullable=False),
    sa.Column('shares', sa.BigInteger(), nullable=False),
    sa.Column('avg_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'symbol', name='uq_holdings_user_symbol')
    )
    op.create_index(op.f('ix_holdings_user_id'), 'holdings', ['user_id'], unique=False)
    op.create_table('aksi_reports',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('mode', sa.String(length=8), nullable=False),
    sa.Column('as_of', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('holdings_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('events', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('credits_spent', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_aksi_reports_user_created', 'aksi_reports', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_aksi_reports_user_created', table_name='aksi_reports')
    op.drop_table('aksi_reports')
    op.drop_index(op.f('ix_holdings_user_id'), table_name='holdings')
    op.drop_table('holdings')
```

- [ ] **Step 5: Schemas**

```python
# backend/app/schemas/aksi.py
import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

_SYMBOL = re.compile(r"^[A-Z]{4}$")
_MIN_DATE = date(2021, 1, 1)


def normalize_symbol(v: Any) -> str:
    s = str(v or "").strip().upper()
    if s.endswith(".JK"):
        s = s[:-3]
    if not _SYMBOL.match(s):
        raise ValueError("symbol must be a 4-letter IDX ticker, e.g. BBCA")
    return s


def _check_as_of(v: date | None) -> date | None:
    if v is not None and not (_MIN_DATE <= v <= date.today()):
        raise ValueError("as_of must be between 2021-01-01 and today")
    return v


class HoldingIn(BaseModel):
    symbol: str
    shares: int = Field(ge=1, le=10**12)
    avg_price: float | None = Field(default=None, gt=0)

    @field_validator("symbol", mode="before")
    @classmethod
    def _symbol(cls, v: Any) -> str:
        return normalize_symbol(v)


class HoldingsIn(BaseModel):
    holdings: list[HoldingIn] = Field(max_length=30)

    @model_validator(mode="after")
    def _unique(self) -> "HoldingsIn":
        symbols = [h.symbol for h in self.holdings]
        if len(symbols) != len(set(symbols)):
            raise ValueError("duplicate symbols")
        return self


class HoldingsOut(BaseModel):
    holdings: list[HoldingIn]


class CheckRequest(BaseModel):
    as_of: date | None = None
    symbols: list[str] | None = Field(default=None, max_length=30)
    budget: int = Field(default=25, ge=5, le=40)

    @field_validator("as_of")
    @classmethod
    def _as_of(cls, v: date | None) -> date | None:
        return _check_as_of(v)

    @field_validator("symbols", mode="before")
    @classmethod
    def _symbols(cls, v: Any) -> list[str] | None:
        return [normalize_symbol(s) for s in v] if v else None


class ReportOut(BaseModel):
    id: str
    mode: str
    as_of: date
    status: str
    holdings_snapshot: list[dict[str, Any]]
    events: list[dict[str, Any]]
    credits_spent: int
    created_at: datetime
    updated_at: datetime


class ImpactRequest(BaseModel):
    symbol: str
    shares: int = Field(ge=1, le=10**12)
    as_of: date | None = None

    @field_validator("symbol", mode="before")
    @classmethod
    def _symbol(cls, v: Any) -> str:
        return normalize_symbol(v)

    @field_validator("as_of")
    @classmethod
    def _as_of(cls, v: date | None) -> date | None:
        return _check_as_of(v)


class ImpactOut(BaseModel):
    symbol: str
    as_of: date
    events: list[dict[str, Any]]
    fetched_at: str | None = None
    note: str
```

- [ ] **Step 6: Store**

```python
# backend/app/aksi/store.py
"""Persistence for holdings and check reports (own sessions, like the cache)."""

import uuid
from datetime import date

from sqlalchemy import delete, select

from app.db.session import async_session_maker
from app.models.aksi_report import AksiReport
from app.models.holding import Holding


def _holding(h: Holding) -> dict:
    return {
        "symbol": h.symbol,
        "shares": int(h.shares),
        "avg_price": float(h.avg_price) if h.avg_price is not None else None,
    }


def _report(r: AksiReport) -> dict:
    return {
        "id": str(r.id),
        "mode": r.mode,
        "as_of": r.as_of.isoformat(),
        "status": r.status,
        "holdings_snapshot": r.holdings_snapshot or [],
        "events": r.events or [],
        "credits_spent": r.credits_spent,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


async def list_holdings(user_id: int) -> list[dict]:
    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(Holding).where(Holding.user_id == user_id).order_by(Holding.symbol)
            )
        ).scalars().all()
    return [_holding(h) for h in rows]


async def replace_holdings(user_id: int, holdings: list[dict]) -> None:
    async with async_session_maker() as db:
        await db.execute(delete(Holding).where(Holding.user_id == user_id))
        db.add_all(
            Holding(user_id=user_id, symbol=h["symbol"], shares=h["shares"],
                    avg_price=h.get("avg_price"))
            for h in holdings
        )
        await db.commit()


async def create_report(user_id: int, mode: str, as_of: date, holdings: list[dict]) -> str:
    async with async_session_maker() as db:
        report = AksiReport(user_id=user_id, mode=mode, as_of=as_of, status="running",
                            holdings_snapshot=holdings, events=[], credits_spent=0)
        db.add(report)
        await db.commit()
        return str(report.id)


async def append_event(report_id: str, result: dict, credits: int) -> None:
    async with async_session_maker() as db:
        report = await db.get(AksiReport, uuid.UUID(report_id))
        if report is None:
            return
        report.events = [*(report.events or []), result]  # new list → change detected
        report.credits_spent = credits
        await db.commit()


async def finish_report(report_id: str, status: str, credits: int | None) -> None:
    async with async_session_maker() as db:
        report = await db.get(AksiReport, uuid.UUID(report_id))
        if report is None:
            return
        report.status = status
        if credits is not None:
            report.credits_spent = credits
        await db.commit()


async def latest_report(user_id: int, mode: str | None = None) -> dict | None:
    stmt = (
        select(AksiReport)
        .where(AksiReport.user_id == user_id, AksiReport.status != "running")
        .order_by(AksiReport.created_at.desc())
        .limit(1)
    )
    if mode:
        stmt = stmt.where(AksiReport.mode == mode)
    async with async_session_maker() as db:
        report = (await db.execute(stmt)).scalars().first()
    return _report(report) if report else None


async def get_report(user_id: int, report_id: str) -> dict | None:
    async with async_session_maker() as db:
        report = await db.get(AksiReport, uuid.UUID(report_id))
    if report is None or report.user_id != user_id:
        return None
    return _report(report)
```

- [ ] **Step 7: Shared SSE helper + chat refactor**

```python
# backend/app/api/sse.py
"""Server-sent events over a detached run's replay buffer (chat + aksi)."""

import json
from typing import Any, AsyncIterator

from fastapi.responses import StreamingResponse

from app.agent.runs import AgentRun

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


async def event_stream(run: AgentRun, last_seq: int = 0) -> AsyncIterator[str]:
    queue = run.subscribe(last_seq)
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield sse(event)
    finally:
        run.unsubscribe(queue)


def sse_response(run: AgentRun, last_seq: int = 0) -> StreamingResponse:
    return StreamingResponse(
        event_stream(run, last_seq), media_type="text/event-stream", headers=SSE_HEADERS
    )
```

In `backend/app/api/v1/endpoints/chat.py`:
- delete `_SSE_HEADERS`, `_sse` and `_event_stream` (lines 32–52) and the `import json`, `AsyncIterator` and `StreamingResponse` imports that become unused;
- add `from app.api.sse import sse_response`;
- replace the two returns:

```python
    return sse_response(run)            # in chat_stream
```
```python
    return sse_response(run, last_seq)  # in thread_stream
```

Run `docker compose exec backend python -m pytest tests/test_chat_api.py -v` → all pass (behaviour unchanged).

- [ ] **Step 8: Holdings routes + router registration**

```python
# backend/app/api/v1/endpoints/aksi.py
"""Aksi Korporasi: holdings, corporate-action checks (SSE), reports, impact."""

from fastapi import APIRouter, Depends

from app.aksi import store
from app.api import deps
from app.models.user import User
from app.schemas.aksi import HoldingsIn, HoldingsOut

router = APIRouter()


@router.get("/holdings", response_model=HoldingsOut)
async def get_holdings(current_user: User = Depends(deps.get_current_user)):
    return {"holdings": await store.list_holdings(current_user.id)}


@router.put("/holdings", response_model=HoldingsOut)
async def put_holdings(body: HoldingsIn, current_user: User = Depends(deps.get_current_user)):
    await store.replace_holdings(current_user.id, [h.model_dump() for h in body.holdings])
    return {"holdings": await store.list_holdings(current_user.id)}
```

```python
# backend/app/api/v1/api.py
from fastapi import APIRouter

from app.api.v1.endpoints import aksi, auth, chat, memory, sectors, users

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(memory.router, prefix="/memories", tags=["memory"])
api_router.include_router(sectors.router, prefix="/sectors", tags=["sectors"])
api_router.include_router(aksi.router, prefix="/aksi", tags=["aksi"])
api_router.include_router(chat.router, tags=["chat"])
```

- [ ] **Step 9: Migrate and run tests**

Run: `docker compose exec backend alembic upgrade head && docker compose exec backend alembic check`
Expected: upgrade succeeds; `No new upgrade operations detected.`
Run: `docker compose exec backend python -m pytest tests/test_aksi_holdings_api.py tests/test_chat_api.py -v`
Expected: all pass.

- [ ] **Step 10: Commit (after user review)**

```bash
git add backend/app/models backend/alembic/versions/20261006_1200_b4e1a7c9d2f3_holdings_aksi_reports.py backend/app/schemas/aksi.py backend/app/aksi/store.py backend/app/api/sse.py backend/app/api/v1/endpoints/chat.py backend/app/api/v1/endpoints/aksi.py backend/app/api/v1/api.py backend/tests/test_aksi_holdings_api.py
git commit -m "phase 14c: holdings + reports persistence, shared sse helper"
```

---

### Task 3: Formatting and events (`fmt.py`, `events.py`)

**Files:**
- Create: `backend/app/aksi/fmt.py`, `backend/app/aksi/events.py`
- Test: `backend/tests/test_aksi_events.py`

**Interfaces:**
- Consumes: `calc.phase`, `calc.parse_date`.
- Produces:
  - `fmt.idr(v, lang="id")`, `fmt.number(v, lang)`, `fmt.pct(ratio, lang)`, `fmt.pct_raw(percent_units, lang)`, `fmt.points(ratio, lang)`, `fmt.day(v, lang)`, `fmt.figure(fig: dict, lang) -> str`
  - `events.KINDS: list[str]`, `events.MAX_EVENTS = 5`, `events.today_wib() -> date`, `events.scan_window(as_of) -> (start, end)`, `events.norm_symbol(raw) -> str`, `events.normalize(calendar: dict, holdings: list[dict], as_of: date) -> list[Event]`, `events.public(ev) -> PublicEvent`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_aksi_events.py
from datetime import date
from decimal import Decimal

from app.aksi import events, fmt

WIFI = {"symbol": "WIFI.JK", "ex_date": "2025-07-02", "cum_date": "2025-07-01",
        "recording_date": "2025-07-03", "trading_period_start": "2025-07-07",
        "trading_period_end": "2025-07-15", "subscription_date": "2025-07-03",
        "price": 2000, "old_ratio": 4, "new_ratio": 5}
BBMD = {"symbol": "BBMD.JK", "ex_date": "2025-07-14", "cum_date": "2025-07-11",
        "recording_date": "2025-07-15", "payment_date": "2025-07-25",
        "dividend_amount": 34.25}
CAL = {"right_issue": [WIFI, {**WIFI, "symbol": "ZZZZ.JK"}],
       "upcoming_dividend": [BBMD], "dividend": [BBMD], "warrant": []}
HOLD = [{"symbol": "WIFI", "shares": 1000}, {"symbol": "BBMD", "shares": 5000, "avg_price": 1900}]


def test_scan_window_spans_90_days():
    assert events.scan_window(date(2025, 7, 10)) == ("2025-06-10", "2025-09-08")


def test_normalize_filters_dedupes_and_orders_by_urgency():
    evs = events.normalize(CAL, HOLD, date(2025, 7, 10))
    assert [e["id"] for e in evs] == ["BBMD:dividend:2025-07-14", "WIFI:right_issue:2025-07-02"]
    assert (evs[0]["urgency"], evs[0]["phase"]) == (1, "before_cum")
    assert (evs[1]["urgency"], evs[1]["phase"]) == (5, "window_open")
    assert evs[0]["avg_price"] == 1900 and evs[1]["shares"] == 1000


def test_finished_events_are_dropped():
    assert events.normalize(CAL, HOLD, date(2025, 7, 30)) == []


def test_cap_at_max_events():
    symbols = [f"AA{c}{c}" for c in "ABCDEFG"]
    cal = {"upcoming_dividend": [{**BBMD, "symbol": f"{s}.JK"} for s in symbols]}
    hold = [{"symbol": s, "shares": 100} for s in symbols]
    assert len(events.normalize(cal, hold, date(2025, 7, 10))) == events.MAX_EVENTS


def test_public_shape():
    ev = events.normalize(CAL, HOLD, date(2025, 7, 10))[1]
    pub = events.public(ev)
    assert pub["event_id"] == ev["id"] and pub["row"]["price"] == 2000
    assert set(pub) == {"event_id", "symbol", "kind", "phase", "shares", "urgency", "row"}


def test_formatting():
    assert fmt.idr(2500000) == "Rp2.500.000"
    assert fmt.idr(2500000, "en") == "Rp2,500,000"
    assert fmt.idr(Decimal("34.25")) == "Rp34,25"
    assert fmt.idr(Decimal("2444.4444")) == "Rp2.444"
    assert fmt.pct(Decimal(5) / Decimal(9)) == "55,56%"
    assert fmt.pct(Decimal(5) / Decimal(9), "en") == "55.56%"
    assert fmt.pct_raw(40.17) == "40,17%"
    assert fmt.points(Decimal("0.01")) == "1,00"
    assert fmt.day("2025-07-15") == "15 Jul 2025"
    assert fmt.day("2025-08-01") == "1 Agu 2025"
    assert fmt.figure({"value": 1250, "unit": "rights"}) == "1.250"
    assert fmt.figure({"value": 5, "unit": "days"}) == "5 hari"
    assert fmt.figure({"value": None, "unit": "IDR"}) == "—"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend python -m pytest tests/test_aksi_events.py -v`
Expected: FAIL with `ImportError` (no `events`/`fmt`).

- [ ] **Step 3: Implement**

```python
# backend/app/aksi/fmt.py
"""ID/EN formatting for figures — Indonesian first, English mirror."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_MONTHS = {
    "id": ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}


def _seps(lang: str) -> tuple[str, str]:
    return (".", ",") if lang == "id" else (",", ".")


def _fixed(d: Decimal, places: int, lang: str) -> str:
    group, decimal_sep = _seps(lang)
    q = abs(d).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    whole, _, frac = f"{q:.{places}f}".partition(".")
    out = f"{int(whole):,}".replace(",", group)
    return out + (decimal_sep + frac if places else "")


def number(value: Any, lang: str = "id") -> str:
    d = Decimal(str(value))
    return ("−" if d < 0 else "") + _fixed(d, 0, lang)


def idr(value: Any, lang: str = "id") -> str:
    """Whole rupiah, except small fractional amounts (per-share dividends)."""
    d = Decimal(str(value))
    places = 2 if abs(d) < 1000 and d != d.to_integral_value() else 0
    return ("−" if d < 0 else "") + "Rp" + _fixed(d, places, lang)


def pct(ratio: Any, lang: str = "id") -> str:
    return _fixed(Decimal(str(ratio)) * 100, 2, lang) + "%"


def pct_raw(percent_units: Any, lang: str = "id") -> str:
    return pct(Decimal(str(percent_units)) / 100, lang)


def points(ratio: Any, lang: str = "id") -> str:
    return _fixed(Decimal(str(ratio)) * 100, 2, lang)


def day(value: Any, lang: str = "id") -> str:
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return f"{d.day} {_MONTHS[lang][d.month - 1]} {d.year}"


def figure(fig: dict, lang: str = "id") -> str:
    value = fig.get("value")
    if value is None:
        return "—"
    unit = fig.get("unit")
    if unit == "IDR":
        return idr(value, lang)
    if unit == "ratio":
        return pct(value, lang)
    if unit == "date":
        return day(value, lang)
    if unit == "days":
        return f"{value} hari" if lang == "id" else f"{value} days"
    return number(value, lang)
```

```python
# backend/app/aksi/events.py
"""Holding-scoped corporate-action events from the Sectors calendar.

One market-wide calendar read covers every holding: rows are filtered to the
user's tickers, deduplicated (a dividend can appear as both `dividend` and
`upcoming_dividend`), phased against `as_of`, and ordered by urgency.
"""

from datetime import date, datetime, timedelta

from app.aksi import calc
from app.sectors.freshness import WIB

KINDS = ["right_issue", "warrant", "upcoming_dividend", "dividend"]
SCAN_BACK_DAYS = 30
SCAN_AHEAD_DAYS = 60  # back + ahead = the calendar's 90-day window cap
MAX_EVENTS = 5
_DONE_PHASES = {"expired", "paid"}
_KEY_DATE = {
    "right_issue": "ex_date",
    "warrant": "trading_period_start",
    "upcoming_dividend": "ex_date",
    "dividend": "ex_date",
}


def today_wib() -> date:
    return datetime.now(WIB).date()


def scan_window(as_of: date) -> tuple[str, str]:
    return (
        (as_of - timedelta(days=SCAN_BACK_DAYS)).isoformat(),
        (as_of + timedelta(days=SCAN_AHEAD_DAYS)).isoformat(),
    )


def norm_symbol(raw: object) -> str:
    return str(raw or "").strip().upper().removesuffix(".JK")


def _family(kind: str) -> str:
    return "dividend" if kind in ("dividend", "upcoming_dividend") else kind


def _urgency(family: str, row: dict, as_of: date) -> int | None:
    if family == "right_issue":
        target = row.get("trading_period_end")
    elif family == "warrant":
        target = row.get("ex_per_end") or row.get("maturity_date")
    else:
        cum = calc.parse_date(row.get("cum_date"))
        target = row.get("cum_date") if cum and as_of <= cum else row.get("payment_date")
    d = calc.parse_date(target)
    return (d - as_of).days if d else None


def normalize(calendar: dict, holdings: list[dict], as_of: date) -> list[dict]:
    held = {norm_symbol(h["symbol"]): h for h in holdings}
    seen: set[str] = set()
    out: list[dict] = []
    for kind in KINDS:
        for row in calendar.get(kind) or []:
            symbol = norm_symbol(row.get("symbol"))
            if symbol not in held:
                continue
            family = _family(kind)
            phase = calc.phase(family, row, as_of)
            if phase in _DONE_PHASES:
                continue
            event_id = f"{symbol}:{family}:{row.get(_KEY_DATE[kind])}"
            if event_id in seen:
                continue
            seen.add(event_id)
            holding = held[symbol]
            out.append({
                "id": event_id,
                "symbol": symbol,
                "kind": family,
                "row": row,
                "phase": phase,
                "shares": int(holding["shares"]),
                "avg_price": holding.get("avg_price"),
                "urgency": _urgency(family, row, as_of),
            })
    out.sort(key=lambda e: (e["urgency"] is None, e["urgency"] or 0))
    return out[:MAX_EVENTS]


def public(ev: dict) -> dict:
    """SSE/report shape — what the UI needs, nothing internal."""
    return {
        "event_id": ev["id"],
        "symbol": ev["symbol"],
        "kind": ev["kind"],
        "phase": ev["phase"],
        "shares": ev["shares"],
        "urgency": ev["urgency"],
        "row": ev["row"],
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec backend python -m pytest tests/test_aksi_events.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit (after user review)**

```bash
git add backend/app/aksi/fmt.py backend/app/aksi/events.py backend/tests/test_aksi_events.py
git commit -m "phase 14d: aksi events + formatting"
```

---

### Task 4: Findings (`findings.py`)

**Files:**
- Create: `backend/app/aksi/findings.py`
- Test: `backend/tests/test_aksi_findings.py`

**Interfaces:**
- Consumes: `calc.parse_decimal`, `calc.close_on_or_before`, `fmt.*`.
- Produces: `rows(envelope) -> list[dict]`, `top_holder(ownership_env) -> str | None`, `controller_change(filings_env, ownership_env, as_of) -> Finding`, `price_vs_exercise(ev, prices_env, as_of) -> Finding | None`, `ownership_shift(shareholders_env, as_of, months=3) -> Finding | None`, `dividend_yield(ev) -> Finding | None`, `extract(ev, pack: dict, extra: list[dict], as_of) -> list[Finding]`. `pack` keys: `prices`, `ownership`, `filings`, `shareholders`. `extra` items: `{"tool", "args", "envelope"}` from the investigate loop.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_aksi_findings.py
from datetime import date

from app.aksi import findings

AS_OF = date(2025, 7, 10)
WIFI = {"price": 2000, "cum_date": "2025-07-01", "trading_period_end": "2025-07-15",
        "old_ratio": 4, "new_ratio": 5}
EV = {"id": "WIFI:right_issue:2025-07-02", "symbol": "WIFI", "kind": "right_issue",
      "row": WIFI, "shares": 1000}


def env(data):
    return {"status": 200, "source": "upstream", "fetched_at": "2025-07-10T17:05:00+07:00", "data": data}


PRICES = env([{"date": "2025-07-01", "close": 3000}, {"date": "2025-07-09", "close": 2310},
              {"date": "2025-07-14", "close": 2100}])
ISB = "PT Investasi Sukses Bersama"
FILINGS = env({"results": [
    {"timestamp": "2025-07-09T10:00:00", "holder_name": ISB, "transaction_type": "buy",
     "share_percentage_before": 40.17, "share_percentage_after": 42.73,
     "amount_transaction": 1480000000, "price": 2000},
    {"timestamp": "2025-06-15T09:00:00", "holder_name": "Budi", "transaction_type": "sell",
     "share_percentage_before": 0.5, "share_percentage_after": 0.4,
     "amount_transaction": 1000000, "price": 2900},
    {"timestamp": "2025-07-14T09:00:00", "holder_name": ISB, "transaction_type": "buy",
     "share_percentage_before": 42.73, "share_percentage_after": 45.0,
     "amount_transaction": 5, "price": 2000},
], "pagination": {}})
OWNERSHIP = env({"symbol": "WIFI.JK", "ownership": {"major_shareholders": [
    {"name": ISB, "share_percentage": 40.17}, {"name": "Masyarakat", "share_percentage": 30.0}]}})
SHARE = env({"symbol": "WIFI.JK", "year": 2025, "data": [
    {"date": "2025-03-31", "shares_number": 1000, "total_f": 100},
    {"date": "2025-04-30", "shares_number": 1000, "total_f": 98},
    {"date": "2025-05-31", "shares_number": 1000, "total_f": 95},
    {"date": "2025-06-30", "shares_number": 1000, "total_f": 90},
    {"date": "2025-07-31", "shares_number": 1000, "total_f": 50},
]})


def test_rows_reads_list_and_nested_results():
    assert len(findings.rows(PRICES)) == 3
    assert len(findings.rows(FILINGS)) == 3
    assert findings.rows({"error": "x"}) == []


def test_top_holder_picks_largest_named_entry():
    assert findings.top_holder(OWNERSHIP) == ISB


def test_controller_change_uses_top_holder_and_ignores_future_rows():
    f = findings.controller_change(FILINGS, OWNERSHIP, AS_OF)
    assert f["values"]["holder"] == ISB and f["values"]["after"] == 42.73
    assert "membeli" in f["text_id"] and "40,17% → 42,73%" in f["text_id"]
    assert "bought" in f["text_en"] and f["source_tool"] == "sectors_insider_filings"


def test_controller_change_without_filings_is_still_a_fact():
    f = findings.controller_change(env({"results": []}), OWNERSHIP, AS_OF)
    assert f["values"]["count"] == 0 and f["text_id"].startswith("Tidak ada")


def test_price_vs_exercise():
    f = findings.price_vs_exercise(EV, PRICES, AS_OF)
    assert f["values"]["close"] == 2310.0 and f["values"]["date"] == "2025-07-09"
    assert "15,50%" in f["text_id"] and "di atas" in f["text_id"]


def test_ownership_shift_until_as_of():
    f = findings.ownership_shift(SHARE, AS_OF)
    assert "turun 1,00 poin" in f["text_id"] and "3 bulan" in f["text_id"]
    assert "10,00% → 9,00%" in f["text_id"]


def test_extract_by_kind():
    pack = {"prices": PRICES, "filings": FILINGS, "ownership": OWNERSHIP, "shareholders": SHARE}
    assert [f["id"] for f in findings.extract(EV, pack, [], AS_OF)] == [
        "controller_change", "price_vs_exercise", "ownership_shift"]
    div = {"kind": "dividend", "row": {"dividend_yield": 0.0168784}}
    out = findings.extract(div, {}, [], AS_OF)
    assert out[0]["id"] == "dividend_yield" and "1,69%" in out[0]["text_id"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend python -m pytest tests/test_aksi_findings.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

```python
# backend/app/aksi/findings.py
"""Deterministic context findings for an event.

Code writes every sentence (with its numbers) — the brief LLM only references
finding ids. Rows dated after `as_of` are ignored so replays never peek ahead.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from app.aksi import calc, fmt

_VERB = {"buy": ("membeli", "bought"), "sell": ("menjual", "sold")}


def rows(envelope: Any) -> list[dict]:
    """Row list from a Sectors envelope: `data` itself, or `data.results`/`data.data`."""
    if not isinstance(envelope, dict):
        return []
    data = envelope.get("data")
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("results", "data"):
            if isinstance(data.get(key), list):
                return [r for r in data[key] if isinstance(r, dict)]
    return []


def _day(r: dict) -> str:
    return str(r.get("timestamp") or r.get("date") or "")[:10]


def _finding(fid: str, text_id: str, text_en: str, values: dict,
             source_tool: str, envelope: Any = None) -> dict:
    return {
        "id": fid,
        "kind": fid,
        "text_id": text_id,
        "text_en": text_en,
        "values": values,
        "source_tool": source_tool,
        "fetched_at": envelope.get("fetched_at") if isinstance(envelope, dict) else None,
    }


def top_holder(ownership_env: Any) -> str | None:
    """Largest named shareholder anywhere in the ownership section."""
    data = ownership_env.get("data") if isinstance(ownership_env, dict) else None
    stack: list[Any] = [data.get("ownership")] if isinstance(data, dict) else []
    best: tuple[str, Decimal] | None = None
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            name = node.get("name")
            pct = calc.parse_decimal(node.get("share_percentage") or node.get("percentage"))
            if name and pct is not None and (best is None or pct > best[1]):
                best = (str(name), pct)
            stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            stack.extend(node)
    return best[0] if best else None


def controller_change(filings_env: Any, ownership_env: Any, as_of: date) -> dict:
    cutoff = as_of.isoformat()
    filings = [r for r in rows(filings_env) if _day(r) and _day(r) <= cutoff]
    if not filings:
        return _finding(
            "controller_change",
            "Tidak ada laporan transaksi orang dalam atau pemegang saham besar pada periode ini.",
            "No insider or major-shareholder filings in this period.",
            {"count": 0}, "sectors_insider_filings", filings_env)
    holder = top_holder(ownership_env)
    matched = [r for r in filings
               if holder and holder.lower() in str(r.get("holder_name") or "").lower()]
    r = max(matched or filings, key=_day)
    name = str(r.get("holder_name") or "Pemegang saham")
    verb_id, verb_en = _VERB.get(str(r.get("transaction_type") or "").lower(),
                                 ("bertransaksi", "transacted"))
    before = calc.parse_decimal(r.get("share_percentage_before"))
    after = calc.parse_decimal(r.get("share_percentage_after"))
    day = _day(r)
    text_id = f"{name} tercatat {verb_id} saham pada {fmt.day(day)}"
    text_en = f"{name} {verb_en} shares on {fmt.day(day, 'en')}"
    if before is not None and after is not None:
        text_id += f": kepemilikan {fmt.pct_raw(before)} → {fmt.pct_raw(after)}"
        text_en += f": ownership {fmt.pct_raw(before, 'en')} → {fmt.pct_raw(after, 'en')}"
    values = {
        "holder": name,
        "transaction_type": r.get("transaction_type"),
        "date": day,
        "before": float(before) if before is not None else None,
        "after": float(after) if after is not None else None,
        "count": len(filings),
    }
    return _finding("controller_change", text_id + ".", text_en + ".", values,
                    "sectors_insider_filings", filings_env)


def price_vs_exercise(ev: dict, prices_env: Any, as_of: date) -> dict | None:
    price = calc.parse_decimal(ev["row"].get("price"))
    close, day = calc.close_on_or_before(rows(prices_env), as_of.isoformat())
    if price is None or price <= 0 or close is None:
        return None
    diff = (close - price) / price
    above = diff >= 0
    text_id = (f"Harga penutupan terakhir {fmt.idr(close)} ({fmt.day(day)}), "
               f"{fmt.pct(abs(diff))} {'di atas' if above else 'di bawah'} "
               f"harga pelaksanaan {fmt.idr(price)}.")
    text_en = (f"Latest close {fmt.idr(close, 'en')} ({fmt.day(day, 'en')}), "
               f"{fmt.pct(abs(diff), 'en')} {'above' if above else 'below'} "
               f"the exercise price {fmt.idr(price, 'en')}.")
    values = {"close": float(close), "date": day, "price": float(price), "diff": float(diff)}
    return _finding("price_vs_exercise", text_id, text_en, values,
                    "sectors_daily_prices", prices_env)


def _foreign_ratio(r: dict) -> Decimal | None:
    total_f = calc.parse_decimal(r.get("total_f"))
    shares = calc.parse_decimal(r.get("shares_number"))
    return total_f / shares if total_f is not None and shares else None


def ownership_shift(shareholders_env: Any, as_of: date, months: int = 3) -> dict | None:
    cutoff = as_of.isoformat()
    series = sorted((r for r in rows(shareholders_env) if _day(r) and _day(r) <= cutoff),
                    key=_day)[-(months + 1):]
    if len(series) < 2:
        return None
    first, last = _foreign_ratio(series[0]), _foreign_ratio(series[-1])
    if first is None or last is None:
        return None
    delta = last - first
    span = len(series) - 1
    up = delta >= 0
    text_id = (f"Porsi investor asing {'naik' if up else 'turun'} {fmt.points(abs(delta))} "
               f"poin persentase dalam {span} bulan ({fmt.pct(first)} → {fmt.pct(last)}).")
    text_en = (f"Foreign ownership {'rose' if up else 'fell'} {fmt.points(abs(delta), 'en')} "
               f"percentage points over {span} months "
               f"({fmt.pct(first, 'en')} → {fmt.pct(last, 'en')}).")
    values = {"from": float(first), "to": float(last), "months": span}
    return _finding("ownership_shift", text_id, text_en, values,
                    "sectors_shareholders", shareholders_env)


def dividend_yield(ev: dict) -> dict | None:
    y = calc.parse_decimal(ev["row"].get("dividend_yield"))
    if y is None:
        return None
    return _finding("dividend_yield", f"Yield dividen menurut data Sectors: {fmt.pct(y)}.",
                    f"Dividend yield per Sectors data: {fmt.pct(y, 'en')}.",
                    {"yield": float(y)}, "sectors_corporate_actions")


def _with_extra(envelope: Any, extra: list[dict], tool: str) -> Any:
    """Merge rows the investigate loop fetched with the same tool (deduplicated)."""
    more = [r for x in extra if x.get("tool") == tool for r in rows(x.get("envelope"))]
    if not more:
        return envelope
    merged, seen = [], set()
    for r in rows(envelope) + more:
        key = (_day(r), r.get("holder_name"), r.get("transaction_type"), r.get("amount_transaction"))
        if key not in seen:
            seen.add(key)
            merged.append(r)
    base = dict(envelope) if isinstance(envelope, dict) else {}
    base["data"] = merged
    return base


def extract(ev: dict, pack: dict, extra: list[dict], as_of: date) -> list[dict]:
    kind = ev["kind"]
    if kind == "right_issue":
        candidates = [
            controller_change(_with_extra(pack.get("filings"), extra, "sectors_insider_filings"),
                              pack.get("ownership"), as_of),
            price_vs_exercise(ev, pack.get("prices"), as_of),
            ownership_shift(_with_extra(pack.get("shareholders"), extra, "sectors_shareholders"),
                            as_of),
        ]
    elif kind == "warrant":
        candidates = [price_vs_exercise(ev, pack.get("prices"), as_of)]
    elif kind == "dividend":
        candidates = [dividend_yield(ev)]
    else:
        candidates = []
    return [c for c in candidates if c]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec backend python -m pytest tests/test_aksi_findings.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit (after user review)**

```bash
git add backend/app/aksi/findings.py backend/tests/test_aksi_findings.py
git commit -m "phase 14e: aksi findings"
```

---

### Task 5: Brief gate and brief writer (`gate.py`, `briefs.py`, prompt)

**Files:**
- Create: `backend/app/aksi/gate.py`, `backend/app/aksi/briefs.py`, `backend/app/prompts/aksi_brief.md`
- Test: `backend/tests/test_aksi_gate.py`

**Interfaces:**
- Consumes: `app.core.jev.jev_ask/Noul`, `app.core.llm.get_chat_model`, `fmt.*`, `calc.figures_for` (tests only).
- Produces:
  - `gate.PLACEHOLDER_RE`, `gate.check(brief: dict, allowed: set[str], finding_ids: set[str]) -> list[str]`, `async gate.judge(summary: str, evidence: list[str]) -> list[str]`
  - `briefs.BriefDraft` (Pydantic), `briefs._writer` (module-level structured-output model; tests monkeypatch it), `briefs.placeholder_values(ev, figures, lang) -> dict[str, str]`, `briefs.allowed_placeholders(ev, figures) -> set[str]`, `briefs.render(draft, ev, figures) -> dict`, `briefs.template(ev) -> dict`, `async briefs.write(ev, figures, found, feedback=None) -> dict | None`, `async briefs.produce(ev, figures, found) -> Brief`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_aksi_gate.py
from datetime import date
from types import SimpleNamespace

import pytest

from app.aksi import briefs, calc, gate

AS_OF = date(2025, 7, 10)
WIFI = {"symbol": "WIFI.JK", "ex_date": "2025-07-02", "cum_date": "2025-07-01",
        "recording_date": "2025-07-03", "trading_period_start": "2025-07-07",
        "trading_period_end": "2025-07-15", "subscription_date": "2025-07-03",
        "price": 2000, "old_ratio": 4, "new_ratio": 5}
EV = {"id": "WIFI:right_issue:2025-07-02", "symbol": "WIFI", "kind": "right_issue",
      "row": WIFI, "shares": 1000, "phase": "window_open"}
DIV_EV = {"id": "BBMD:dividend:2025-07-14", "symbol": "BBMD", "kind": "dividend", "shares": 5000,
          "phase": "before_cum", "row": {"symbol": "BBMD.JK", "ex_date": "2025-07-14",
          "cum_date": "2025-07-11", "recording_date": "2025-07-15",
          "payment_date": "2025-07-25", "dividend_amount": 34.25}}
WAR_EV = {"id": "ABCD:warrant:2025-01-10", "symbol": "ABCD", "kind": "warrant", "shares": 1000,
          "phase": "window_open", "row": {"symbol": "ABCD.JK", "trading_period_start": "2025-01-10",
          "ex_per_start": "2025-07-01", "ex_per_end": "2026-01-09",
          "maturity_date": "2026-01-09", "price": 150}}
PRICES = [{"date": "2025-07-01", "close": 3000}, {"date": "2025-07-09", "close": 180}]
FIGS = calc.figures_for(EV, PRICES, AS_OF)


def good_draft() -> dict:
    return {
        "headline_id": "HMETD {{symbol}}: {{rights_entitled}} hak",
        "headline_en": "{{symbol}} rights: {{rights_entitled}}",
        "summary_id": "Jika ditebus semua, dana yang dibutuhkan {{cost_to_exercise_all}} sampai {{trading_period_end}}.",
        "summary_en": "Exercising all rights needs {{cost_to_exercise_all}} by {{trading_period_end}}.",
        "context_ids": ["controller_change"],
        "verify_id": ["Batas waktu internal broker"],
        "verify_en": ["Your broker's internal cut-off"],
    }


def test_check_passes_clean_draft():
    assert gate.check(good_draft(), briefs.allowed_placeholders(EV, FIGS), {"controller_change"}) == []


def test_check_flags_digits_banned_words_and_unknowns():
    d = good_draft()
    d["summary_id"] = "Sebaiknya tebus 1250 HMETD {{magic}}."
    d["context_ids"] = ["nope"]
    reasons = gate.check(d, briefs.allowed_placeholders(EV, FIGS), {"controller_change"})
    assert {"digits_outside_placeholders", "banned_phrase:sebaiknya",
            "unknown_placeholder:magic", "unknown_finding:nope"} <= set(reasons)


def test_templates_always_pass_the_gate():
    for ev in (EV, DIV_EV, WAR_EV):
        figs = calc.figures_for(ev, PRICES, AS_OF)
        assert gate.check(briefs.template(ev), briefs.allowed_placeholders(ev, figs), set()) == [], ev["kind"]


def test_render_substitutes_per_language():
    out = briefs.render(good_draft(), EV, FIGS)
    assert out["summary_id"] == "Jika ditebus semua, dana yang dibutuhkan Rp2.500.000 sampai 15 Jul 2025."
    assert out["summary_en"] == "Exercising all rights needs Rp2,500,000 by 15 Jul 2025."
    assert out["headline_id"] == "HMETD WIFI: 1.250 hak"


@pytest.mark.asyncio
async def test_judge_reasons_and_fail_open(monkeypatch):
    async def strict(state, questions):
        return SimpleNamespace(nouls={"advice": SimpleNamespace(noul=0.8),
                                      "grounded": SimpleNamespace(noul=0.2)})

    async def missing(state, questions):
        return None

    monkeypatch.setattr(gate, "jev_ask", strict)
    assert await gate.judge("x", []) == ["advice_language", "ungrounded"]
    monkeypatch.setattr(gate, "jev_ask", missing)
    assert await gate.judge("x", []) == []


@pytest.mark.asyncio
async def test_produce_accepts_good_draft_and_falls_back_on_bad(monkeypatch):
    class Writer:
        def __init__(self, draft):
            self.draft = draft

        async def ainvoke(self, messages, config=None):
            return briefs.BriefDraft(**self.draft)

    async def missing(state, questions):
        return None

    monkeypatch.setattr(gate, "jev_ask", missing)
    monkeypatch.setattr(briefs, "_writer", Writer(good_draft()))
    found = [{"id": "controller_change", "kind": "controller_change", "text_id": "x"}]
    ok = await briefs.produce(EV, FIGS, found)
    assert ok["gate"] == {"passed": True, "reasons": [], "template": False}

    bad = {**good_draft(), "summary_id": "Harus tebus 1250 hak."}
    monkeypatch.setattr(briefs, "_writer", Writer(bad))
    fallback = await briefs.produce(EV, FIGS, found)
    assert fallback["gate"]["template"] is True
    assert "1.250 HMETD" in fallback["summary_id"]
    assert fallback["context_ids"] == ["controller_change"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend python -m pytest tests/test_aksi_gate.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the gate**

```python
# backend/app/aksi/gate.py
"""Brief gate — deterministic checks first, then one JEV judgment.

The LLM may only write placeholders (`{{name}}`) for numbers and dates; any
digit, advice word, unknown placeholder or unknown finding id rejects the
draft. JEV then checks for advice language and grounding (fail-open when JEV
is unavailable — the deterministic checks already ran).
"""

import re

from app.core.jev import Noul, jev_ask

BANNED = (
    "sebaiknya", "disarankan", "rekomendasi", "saran", "layak", "wajib", "harus",
    "jangan", "segera", "tahan", "beli sekarang", "jual sekarang", "cuan",
    "untung pasti", "should", "must", "recommend", "advise", "worth it",
    "buy now", "sell now",
)
_BANNED_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in BANNED) + r")\b", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
_DIGIT_RE = re.compile(r"\d")
TEXT_FIELDS = ("headline_id", "headline_en", "summary_id", "summary_en")
LIST_FIELDS = ("verify_id", "verify_en")


def _texts(brief: dict) -> list[str]:
    return [str(brief.get(k) or "") for k in TEXT_FIELDS] + [
        str(x) for k in LIST_FIELDS for x in (brief.get(k) or [])
    ]


def check(brief: dict, allowed: set[str], finding_ids: set[str]) -> list[str]:
    reasons: set[str] = set()
    for text in _texts(brief):
        if _DIGIT_RE.search(PLACEHOLDER_RE.sub("", text)):
            reasons.add("digits_outside_placeholders")
        for name in PLACEHOLDER_RE.findall(text):
            if name not in allowed:
                reasons.add(f"unknown_placeholder:{name}")
        for match in _BANNED_RE.findall(text):
            reasons.add(f"banned_phrase:{match.lower()}")
    for fid in brief.get("context_ids") or []:
        if fid not in finding_ids:
            reasons.add(f"unknown_finding:{fid}")
    return sorted(reasons)


async def judge(summary: str, evidence: list[str]) -> list[str]:
    result = await jev_ask(
        {"brief": summary, "evidence": evidence},
        {
            "advice": Noul(instructions=(
                "Does the brief urge or advise the reader to buy, sell, hold, "
                "exercise, or not exercise a security?")),
            "grounded": Noul(instructions=(
                "Is every statement in the brief supported by the evidence list?")),
        },
    )
    if result is None:
        return []
    reasons = []
    advice = result.nouls.get("advice")
    grounded = result.nouls.get("grounded")
    if advice is not None and float(advice.noul) >= 0.3:
        reasons.append("advice_language")
    if grounded is not None and float(grounded.noul) < 0.6:
        reasons.append("ungrounded")
    return reasons
```

- [ ] **Step 4: Implement the brief writer**

```python
# backend/app/aksi/briefs.py
"""Briefs: the LLM drafts with placeholders only; code fills every number.

`produce` runs draft → gate → (one retry with the rejection reasons) → and
falls back to a fixed template, so a brief always exists and never carries an
LLM-written number or advice.
"""

import json
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.aksi import fmt, gate
from app.core.config import settings
from app.core.llm import get_chat_model

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent.parent / "prompts" / "aksi_brief.md").read_text(encoding="utf-8")

_ROW_MONEY = ("price", "dividend_amount")
_ROW_NUMBER = ("old_ratio", "new_ratio")
_ROW_DATES = (
    "cum_date", "ex_date", "recording_date", "trading_period_start", "trading_period_end",
    "payment_date", "ex_per_start", "ex_per_end", "maturity_date",
)


class BriefDraft(BaseModel):
    headline_id: str = Field(description="Indonesian headline, at most 12 words, no digits")
    headline_en: str = Field(description="English headline, at most 12 words, no digits")
    summary_id: str = Field(description="Indonesian summary, at most 90 words, no digits")
    summary_en: str = Field(description="English summary, at most 90 words, no digits")
    context_ids: list[str] = Field(default_factory=list)
    verify_id: list[str] = Field(default_factory=list)
    verify_en: list[str] = Field(default_factory=list)


_writer = get_chat_model(
    settings.MODEL_NAME, temperature=0.2, timeout=60, max_retries=1, reasoning_effort="none",
).with_structured_output(BriefDraft)

TEMPLATES: dict[str, dict] = {
    "right_issue": {
        "headline_id": "Rights issue {{symbol}}: {{rights_entitled}} HMETD untuk posisimu",
        "headline_en": "{{symbol}} rights issue: {{rights_entitled}} rights for your position",
        "summary_id": (
            "Dengan {{shares}} saham, kamu tercatat berhak atas {{rights_entitled}} HMETD "
            "(rasio {{old_ratio}}:{{new_ratio}}) dengan harga pelaksanaan {{price}}. Menebus "
            "semua hak membutuhkan {{cost_to_exercise_all}}. HMETD dapat diperdagangkan atau "
            "dilaksanakan sampai {{trading_period_end}}; jika dibiarkan, hak hangus dan porsi "
            "kepemilikan turun {{dilution_if_ignored}}."
        ),
        "summary_en": (
            "With {{shares}} shares you are entitled to {{rights_entitled}} rights (ratio "
            "{{old_ratio}}:{{new_ratio}}) at an exercise price of {{price}}. Exercising all of "
            "them costs {{cost_to_exercise_all}}. Rights can be traded or exercised until "
            "{{trading_period_end}}; if left alone they lapse and your ownership falls by "
            "{{dilution_if_ignored}}."
        ),
        "verify_id": ["Batas waktu internal broker untuk instruksi penebusan",
                      "Ketentuan pemesanan saham tambahan di prospektus"],
        "verify_en": ["Your broker's internal cut-off for exercise instructions",
                      "Additional-share subscription terms in the prospectus"],
    },
    "dividend": {
        "headline_id": "Dividen {{symbol}}: {{gross_dividend}} bruto untuk posisimu",
        "headline_en": "{{symbol}} dividend: {{gross_dividend}} gross for your position",
        "summary_id": (
            "Dividen {{dividend_amount}} per saham. Untuk {{shares}} saham, jumlah bruto "
            "{{gross_dividend}}. Tanggal cum {{cum_date}}, pembayaran {{payment_date}}. "
            "Jumlah bersih tergantung status pajakmu."
        ),
        "summary_en": (
            "Dividend of {{dividend_amount}} per share. For {{shares}} shares the gross amount "
            "is {{gross_dividend}}. Cum date {{cum_date}}, payment {{payment_date}}. The net "
            "amount depends on your tax status."
        ),
        "verify_id": ["Ketentuan pajak dividen yang berlaku untukmu (DJP)"],
        "verify_en": ["Dividend tax rules that apply to you (DJP)"],
    },
    "warrant": {
        "headline_id": "Waran {{symbol}}: harga pelaksanaan {{price}}",
        "headline_en": "{{symbol}} warrant: exercise price {{price}}",
        "summary_id": (
            "Periode pelaksanaan waran berakhir {{deadline}}. Nilai intrinsik per waran saat "
            "ini {{intrinsic_per_warrant}}. Waran yang tidak dilaksanakan sampai jatuh tempo "
            "menjadi tidak bernilai."
        ),
        "summary_en": (
            "The warrant exercise period ends {{deadline}}. Current intrinsic value per warrant "
            "is {{intrinsic_per_warrant}}. Warrants not exercised by maturity expire worthless."
        ),
        "verify_id": ["Rasio dan ketentuan waran di prospektus"],
        "verify_en": ["Warrant ratio and terms in the prospectus"],
    },
}


def placeholder_values(ev: dict, figures: dict, lang: str) -> dict[str, str]:
    row = ev["row"]
    values = {"symbol": ev["symbol"], "shares": fmt.number(ev["shares"], lang)}
    for key in _ROW_MONEY:
        if row.get(key) is not None:
            values[key] = fmt.idr(row[key], lang)
    for key in _ROW_NUMBER:
        if row.get(key) is not None:
            values[key] = fmt.number(row[key], lang)
    for key in _ROW_DATES:
        if row.get(key):
            values[key] = fmt.day(row[key], lang)
    for key, fig in figures.items():
        values[key] = fmt.figure(fig, lang)
    return values


def allowed_placeholders(ev: dict, figures: dict) -> set[str]:
    return set(placeholder_values(ev, figures, "id"))


def render(draft: dict, ev: dict, figures: dict) -> dict:
    vid = placeholder_values(ev, figures, "id")
    ven = placeholder_values(ev, figures, "en")

    def sub(text: str, values: dict[str, str]) -> str:
        return gate.PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), "—"), text)

    return {
        "headline_id": sub(draft["headline_id"], vid),
        "headline_en": sub(draft["headline_en"], ven),
        "summary_id": sub(draft["summary_id"], vid),
        "summary_en": sub(draft["summary_en"], ven),
        "verify_id": [sub(x, vid) for x in draft.get("verify_id") or []],
        "verify_en": [sub(x, ven) for x in draft.get("verify_en") or []],
        "context_ids": list(draft.get("context_ids") or []),
    }


def template(ev: dict) -> dict:
    return {**TEMPLATES[ev["kind"]], "context_ids": []}


async def write(ev: dict, figures: dict, found: list[dict],
                feedback: list[str] | None = None) -> dict | None:
    payload = {
        "event": {"symbol": ev["symbol"], "kind": ev["kind"], "phase": ev["phase"]},
        "placeholders": sorted(allowed_placeholders(ev, figures)),
        "figures": {k: {"formula": v["formula"], "missing": v["gap"] is not None}
                    for k, v in figures.items()},
        "findings": [{"id": f["id"], "kind": f["kind"]} for f in found],
        "feedback": feedback or [],
    }
    try:
        draft = await _writer.ainvoke(
            [SystemMessage(content=_PROMPT), HumanMessage(content=json.dumps(payload))]
        )
    except Exception:
        logger.warning("aksi brief: writer failed", exc_info=True)
        return None
    return draft.model_dump()


async def produce(ev: dict, figures: dict, found: list[dict]) -> dict:
    allowed = allowed_placeholders(ev, figures)
    finding_ids = {f["id"] for f in found}
    feedback: list[str] | None = None
    reasons: list[str] = []
    accepted: dict | None = None
    for _ in range(2):
        draft = await write(ev, figures, found, feedback)
        if draft is None:
            reasons = ["writer_unavailable"]
            break
        reasons = gate.check(draft, allowed, finding_ids)
        if not reasons:
            summary = render(draft, ev, figures)["summary_id"]
            reasons = await gate.judge(summary, [f.get("text_id", "") for f in found])
        if not reasons:
            accepted = draft
            break
        feedback = reasons
    out = render(accepted or template(ev), ev, figures)
    if accepted is None:
        out["context_ids"] = [f["id"] for f in found]
    out["gate"] = {"passed": accepted is not None, "reasons": reasons,
                   "template": accepted is None}
    return out
```

- [ ] **Step 5: Write the prompt**

````markdown
<!-- backend/app/prompts/aksi_brief.md -->
You write a short, neutral brief about one corporate action for an Indonesian retail investor who holds the stock. Indonesian first, with an English mirror.

You receive JSON with: the event (`symbol`, `kind`, `phase`), `placeholders` (the ONLY names you may use for numbers and dates), `figures` (what each figure means and whether it is missing), `findings` (ids and kinds of context facts already shown to the user next to your text), and `feedback` (reasons a previous draft was rejected — fix them).

Hard rules — a draft breaking any of them is rejected automatically:
1. Write no digits at all. Every number or date must be a placeholder written exactly as `{{name}}`, using only names from `placeholders`.
2. Never advise. Do not tell the reader to buy, sell, hold, exercise, or not exercise. Forbidden words include: sebaiknya, disarankan, rekomendasi, saran, layak, wajib, harus, jangan, segera, tahan, cuan, should, must, recommend, advise, worth it.
3. Use neutral conditionals: "Jika ditebus…", "Jika dijual…", "Jika dibiarkan…" / "If exercised…", "If sold…", "If left alone…".
4. Do not restate findings. Reference the relevant ones by id in `context_ids`, using only ids from `findings`.
5. Never speculate about motives or future prices. If a figure is missing, do not mention it.

Fields:
- `headline_id` / `headline_en`: at most twelve words.
- `summary_id` / `summary_en`: at most ninety words — what the event means for the holder's shares, the key amounts (via placeholders) and the deadline.
- `context_ids`: supporting finding ids, most relevant first.
- `verify_id` / `verify_en`: one to three short things the reader should check themselves (e.g. broker cut-off time, prospectus terms, tax status).
````

(Save the file without the HTML comment line.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `docker compose exec backend python -m pytest tests/test_aksi_gate.py -v`
Expected: 6 passed.

- [ ] **Step 7: Commit (after user review)**

```bash
git add backend/app/aksi/gate.py backend/app/aksi/briefs.py backend/app/prompts/aksi_brief.md backend/tests/test_aksi_gate.py
git commit -m "phase 14f: aksi brief writer + gate"
```

---

### Task 6: Raw sources, budget, graph nodes, graph

**Files:**
- Create: `backend/app/aksi/sources.py`, `backend/app/aksi/budget.py`, `backend/app/aksi/nodes.py`, `backend/app/aksi/graph.py`, `backend/app/prompts/aksi_investigate.md`
- Create: `backend/tests/aksi_fixtures.py` (shared test fixtures)
- Test: `backend/tests/test_aksi_graph.py`

**Interfaces:**
- Consumes: `app.sectors.cache.cached_get`, `app.sectors.tools` (investigate allowlist), Tasks 1–5.
- Produces:
  - `sources.calendar(types, start, end)`, `sources.daily_prices(symbol, start, end)`, `sources.insider_filings(symbol, start, end, limit=30)`, `sources.shareholders(symbol, year)`, `sources.company_report(symbol, sections)` → envelope dicts `{status, source, stale, fetched_at, data}` or `{"error": ...}`. They use the **same path + params as the chat tools**, so cache entries are shared, but **no truncation** (the tools cut payloads at ~12k chars for the LLM).
  - `budget.DEFAULT_BUDGET = 25`, `budget.estimate(name, args) -> int`, `budget.cost(name, args, envelope) -> int`
  - `nodes.scan/context/investigate/compute/brief/persist(state, config)`, `nodes._investigator` (tests monkeypatch), `nodes.base_pack(ev, as_of)`
  - `graph.AksiState`, `graph.aksi_graph` (compiled), `graph.RECURSION_LIMIT = 100`
  - Nodes read `config["configurable"]["emit"]: Callable[[str, Any], None]`.

- [ ] **Step 1: Shared fixtures**

```python
# backend/tests/aksi_fixtures.py
"""Shared upstream fixtures for the Aksi tests — shapes per docs.sectors.app."""

from langchain_core.messages import AIMessage

from app.aksi import briefs, gate, nodes
from app.sectors import client

AS_OF = "2025-07-10"
ISB = "PT Investasi Sukses Bersama"
WIFI_RIGHTS = {"symbol": "WIFI.JK", "ex_date": "2025-07-02", "cum_date": "2025-07-01",
               "recording_date": "2025-07-03", "trading_period_start": "2025-07-07",
               "trading_period_end": "2025-07-15", "subscription_date": "2025-07-03",
               "price": 2000, "old_ratio": 4, "new_ratio": 5}
BBMD_DIVIDEND = {"symbol": "BBMD.JK", "ex_date": "2025-07-14", "cum_date": "2025-07-11",
                 "recording_date": "2025-07-15", "payment_date": "2025-07-25",
                 "dividend_amount": 34.25}
CALENDAR = {"start": "2025-06-10", "end": "2025-09-08", "right_issue": [WIFI_RIGHTS],
            "warrant": [], "upcoming_dividend": [BBMD_DIVIDEND], "dividend": []}
WIFI_PRICES = [{"symbol": "WIFI.JK", "date": "2025-06-30", "close": 2950},
               {"symbol": "WIFI.JK", "date": "2025-07-01", "close": 3000},
               {"symbol": "WIFI.JK", "date": "2025-07-02", "close": 2460},
               {"symbol": "WIFI.JK", "date": "2025-07-09", "close": 2310}]
BBMD_PRICES = [{"symbol": "BBMD.JK", "date": "2025-07-09", "close": 2030}]
OWNERSHIP = {"symbol": "WIFI.JK", "ownership": {"major_shareholders": [
    {"name": ISB, "share_percentage": 40.17}]}}
FILINGS = {"results": [{"symbol": "WIFI.JK", "timestamp": "2025-07-09T10:00:00",
                        "holder_name": ISB, "holder_type": "insider", "transaction_type": "buy",
                        "amount_transaction": 1480000000, "price": 2000,
                        "share_percentage_before": 40.17, "share_percentage_after": 42.73}],
           "pagination": {}}
SHAREHOLDERS = {"symbol": "WIFI.JK", "year": 2025, "data": [
    {"date": "2025-03-31", "shares_number": 2360000000, "total_f": 236000000},
    {"date": "2025-04-30", "shares_number": 2360000000, "total_f": 230000000},
    {"date": "2025-05-31", "shares_number": 2360000000, "total_f": 224000000},
    {"date": "2025-06-30", "shares_number": 2360000000, "total_f": 212400000}]}

ROUTES = {
    "/v2/corporate-actions/": CALENDAR,
    "/v2/daily/WIFI/": WIFI_PRICES,
    "/v2/daily/BBMD/": BBMD_PRICES,
    "/v2/company/report/WIFI/": OWNERSHIP,
    "/v2/filings/": FILINGS,
    "/v2/company/shareholders-composition/WIFI/": SHAREHOLDERS,
}

GOOD_DRAFT = {
    "headline_id": "HMETD {{symbol}}: {{rights_entitled}} hak",
    "headline_en": "{{symbol}} rights: {{rights_entitled}}",
    "summary_id": "Jika ditebus semua, dana yang dibutuhkan {{cost_to_exercise_all}} sampai {{trading_period_end}}.",
    "summary_en": "Exercising all rights needs {{cost_to_exercise_all}} by {{trading_period_end}}.",
    "context_ids": ["controller_change"],
    "verify_id": ["Batas waktu internal broker"],
    "verify_en": ["Your broker's internal cut-off"],
}


def fake_get(calls: list | None = None):
    async def fake(path, params=None):
        if calls is not None:
            calls.append(path)
        if path in ROUTES:
            return 200, ROUTES[path]
        return 404, {"error": "not found"}
    return fake


class FakeWriter:
    async def ainvoke(self, messages, config=None):
        return briefs.BriefDraft(**GOOD_DRAFT)


class FakeInvestigator:
    async def ainvoke(self, messages, config=None):
        return AIMessage(content="enough context")


async def no_jev(state, questions):
    return None


def install_fakes(monkeypatch, calls: list | None = None) -> None:
    monkeypatch.setattr(client, "get", fake_get(calls))
    monkeypatch.setattr(nodes, "_investigator", FakeInvestigator())
    monkeypatch.setattr(briefs, "_writer", FakeWriter())
    monkeypatch.setattr(gate, "jev_ask", no_jev)
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_aksi_graph.py
"""The aksi graph end to end: real tools + cache, mocked upstream/LLM/JEV."""

import json
from datetime import date

import pytest
import pytest_asyncio

from app.aksi import sources, store
from app.aksi.graph import RECURSION_LIMIT, aksi_graph
from app.sectors import tools as st
from tests import aksi_fixtures as fx

pytestmark = pytest.mark.asyncio

HOLDINGS = [{"symbol": "WIFI", "shares": 1000, "avg_price": None},
            {"symbol": "BBMD", "shares": 5000, "avg_price": None}]


@pytest_asyncio.fixture(autouse=True)
async def _bind(bound_session_maker):
    yield


def _state(report_id: str, user_id: int, holdings: list[dict]) -> dict:
    return {"report_id": report_id, "user_id": user_id, "mode": "replay", "as_of": fx.AS_OF,
            "holdings": holdings, "events": [], "cursor": 0, "work": {}, "results": [],
            "credits_used": 0, "budget": 25}


async def _run(user, holdings):
    emitted: list[tuple[str, object]] = []
    report_id = await store.create_report(user.id, "replay", date(2025, 7, 10), holdings)
    final = await aksi_graph.ainvoke(
        _state(report_id, user.id, holdings),
        {"configurable": {"emit": lambda t, d: emitted.append((t, d))},
         "recursion_limit": RECURSION_LIMIT},
    )
    return final, emitted, report_id


async def test_graph_processes_every_event(db, user, monkeypatch):
    fx.install_fakes(monkeypatch)
    final, emitted, report_id = await _run(user, HOLDINGS)

    assert [r["event"]["event_id"] for r in final["results"]] == [
        "BBMD:dividend:2025-07-14", "WIFI:right_issue:2025-07-02"]
    assert final["credits_used"] == 9  # calendar 4 + BBMD prices 1 + WIFI pack 4
    types = [t for t, _ in emitted]
    assert types.count("event_found") == 2 and types.count("numbers") == 2
    assert types.count("brief") == 2 and "budget" in types

    dividend, rights = final["results"]
    assert dividend["figures"]["gross_dividend"]["value"] == 171250
    assert dividend["brief"]["gate"]["template"] is True  # rights-issue draft doesn't fit
    assert rights["figures"]["rights_entitled"]["value"] == 1250
    assert rights["figures"]["terp"]["inputs"]["p_cum"] == 3000
    assert [f["id"] for f in rights["findings"]] == [
        "controller_change", "price_vs_exercise", "ownership_shift"]
    assert rights["brief"]["gate"]["template"] is False
    assert "Rp2.500.000" in rights["brief"]["summary_id"]

    report = await store.get_report(user.id, report_id)
    assert len(report["events"]) == 2 and report["credits_spent"] == 9


async def test_graph_without_matching_events_stops_after_scan(db, user, monkeypatch):
    fx.install_fakes(monkeypatch)
    final, emitted, _ = await _run(user, [{"symbol": "TLKM", "shares": 100, "avg_price": None}])
    assert final["results"] == [] and final["credits_used"] == 4
    assert [d["name"] for t, d in emitted if t == "tool" and d.get("status") == "call"] == [
        "sectors_corporate_actions"]


async def test_sources_share_cache_entries_with_tools(db, monkeypatch):
    calls: list[str] = []
    fx.install_fakes(monkeypatch, calls)
    raw = await sources.daily_prices("WIFI", "2025-04-12", "2025-07-10")
    out = json.loads(await st.sectors_daily_prices.ainvoke(
        {"symbol": "WIFI", "start": "2025-04-12", "end": "2025-07-10"}))
    assert raw["source"] == "upstream" and out["source"] == "hit"
    assert calls == ["/v2/daily/WIFI/"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `docker compose exec backend python -m pytest tests/test_aksi_graph.py -v`
Expected: FAIL with `ImportError` (no `app.aksi.graph`).

- [ ] **Step 4: Implement sources and budget**

```python
# backend/app/aksi/sources.py
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
```

```python
# backend/app/aksi/budget.py
"""Per-run credit accounting — only upstream (non-cache) responses cost."""

DEFAULT_BUDGET = 25

_COST = {
    "sectors_company_corporate_actions": 1,
    "sectors_insider_filings": 1,
    "sectors_shareholders": 1,
    "sectors_daily_prices": 1,
    "sectors_news": 1,
    "sectors_broker_top": 2,
}


def estimate(name: str, args: dict) -> int:
    if name == "sectors_corporate_actions":
        return max(1, len(args.get("types") or []))
    if name == "sectors_company_report":
        return max(1, len(args.get("sections") or []))
    return _COST.get(name, 1)


def cost(name: str, args: dict, envelope: dict) -> int:
    return estimate(name, args) if envelope.get("source") == "upstream" else 0
```

- [ ] **Step 5: Implement the investigate prompt**

````markdown
<!-- backend/app/prompts/aksi_investigate.md -->
You are the context-gathering step of an Indonesian corporate-action assistant. You never give advice and never write user-facing text.

You receive JSON with `as_of` (the analysis date), `event` (a rights issue affecting the user's holding, including its Sectors calendar row), `base_pack` (datasets already fetched and how many rows each returned) and `credits_left`.

Make sure these questions can be answered from data, calling at most a few extra tools, then stop:
1. Did the controlling shareholder (or another major holder) file insider transactions around this rights issue?
2. Did foreign or institutional ownership move noticeably over the last three months?
3. Where is the latest price relative to the exercise price?
4. Has this company done rights issues before (its corporate-action history)?
5. Only if credits allow: news explaining the use of proceeds.

Rules:
- Only call a tool when the base pack lacks data needed for one of the questions (for example, the filings window returned no rows and a wider window is reasonable, or the company history is unknown).
- Never request dates after `as_of`. Keep windows small. Never pass `refresh=true`.
- Every call costs credits; stop when `credits_left` would drop below five.
- When done, reply with one short sentence and no tool calls.
````

(Save the file without the HTML comment line.)

- [ ] **Step 6: Implement the nodes**

```python
# backend/app/aksi/nodes.py
"""Aksi graph nodes: scan → context → investigate → compute → brief → persist.

Nodes report progress through `config["configurable"]["emit"]` (the run's SSE
emitter). Upstream reads emit `tool` events with the chat tools' names and
shape, so the Spark status line narrates them unchanged.
"""

import asyncio
import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from app.aksi import briefs, budget, calc, events, findings, sources, store
from app.core.config import settings
from app.core.llm import get_chat_model
from app.sectors import tools as st

logger = logging.getLogger(__name__)

Emit = Callable[[str, Any], None]
Fetch = Callable[[], Awaitable[dict]]

_INVESTIGATE_PROMPT = (
    Path(__file__).parent.parent / "prompts" / "aksi_investigate.md"
).read_text(encoding="utf-8")
INVESTIGATE_TOOLS = [
    st.sectors_insider_filings, st.sectors_shareholders, st.sectors_daily_prices,
    st.sectors_company_corporate_actions, st.sectors_news, st.sectors_broker_top,
]
_TOOLS_BY_NAME = {t.name: t for t in INVESTIGATE_TOOLS}
MAX_INVESTIGATE_ROUNDS = 2
_investigator = get_chat_model(
    settings.MODEL_NAME, temperature=0, timeout=60, max_retries=1, reasoning_effort="none",
).bind_tools(INVESTIGATE_TOOLS)


def _emit(config: RunnableConfig) -> Emit:
    return (config.get("configurable") or {}).get("emit") or (lambda *_: None)


def _as_of(state: dict) -> date:
    return date.fromisoformat(state["as_of"])


async def _fetch(name: str, args: dict, run: Fetch, *, emit: Emit,
                 ledger: list[int], cap: int) -> dict:
    """Budget-guarded upstream read with chat-shaped `tool` events."""
    if sum(ledger) + budget.estimate(name, args) > cap:
        return {"error": "budget_exhausted"}
    emit("tool", {"name": name, "args": args, "status": "call"})
    try:
        envelope = await run()
    except Exception:
        logger.exception("aksi fetch %s failed", name)
        envelope = {"error": "fetch_failed"}
    emit("tool", {"name": name, "status": "done"})
    ledger.append(budget.cost(name, args, envelope))
    return envelope


def _budget(emit: Emit, ledger: list[int], cap: int) -> None:
    emit("budget", {"credits_used": sum(ledger), "budget": cap})


def _clamp(args: dict, as_of: date) -> dict:
    """Anti-lookahead for replays: no window may end after as_of."""
    out = dict(args)
    if out.get("end") and str(out["end"])[:10] > as_of.isoformat():
        out["end"] = as_of.isoformat()
    if isinstance(out.get("year"), int) and out["year"] > as_of.year:
        out["year"] = as_of.year
    out.pop("refresh", None)
    return out


def base_pack(ev: dict, as_of: date) -> list[tuple[str, str, dict, Fetch]]:
    """(pack key, tool name, args, fetch) — deterministic context per event."""
    sym, row = ev["symbol"], ev["row"]
    p_start, p_end = (as_of - timedelta(days=89)).isoformat(), as_of.isoformat()
    plan: list[tuple[str, str, dict, Fetch]] = [
        ("prices", "sectors_daily_prices", {"symbol": sym, "start": p_start, "end": p_end},
         lambda: sources.daily_prices(sym, p_start, p_end)),
    ]
    if ev["kind"] != "right_issue":
        return plan
    cum = calc.parse_date(row.get("cum_date")) or as_of
    tpe = calc.parse_date(row.get("trading_period_end")) or as_of
    f_end = min(as_of, tpe + timedelta(days=14))
    f_start = min(cum - timedelta(days=60), f_end - timedelta(days=1))
    fs, fe, year = f_start.isoformat(), f_end.isoformat(), as_of.year
    return plan + [
        ("ownership", "sectors_company_report", {"symbol": sym, "sections": ["ownership"]},
         lambda: sources.company_report(sym, ["ownership"])),
        ("filings", "sectors_insider_filings", {"symbol": sym, "start": fs, "end": fe},
         lambda: sources.insider_filings(sym, fs, fe)),
        ("shareholders", "sectors_shareholders", {"symbol": sym, "year": year},
         lambda: sources.shareholders(sym, year)),
    ]


async def scan(state: dict, config: RunnableConfig) -> dict:
    emit, as_of = _emit(config), _as_of(state)
    emit("step", {"node": "scan"})
    ledger = [state["credits_used"]]
    start, end = events.scan_window(as_of)
    args = {"types": list(events.KINDS), "start": start, "end": end}
    envelope = await _fetch("sectors_corporate_actions", args,
                            lambda: sources.calendar(events.KINDS, start, end),
                            emit=emit, ledger=ledger, cap=state["budget"])
    data = envelope.get("data")
    found = events.normalize(data if isinstance(data, dict) else {}, state["holdings"], as_of)
    for ev in found:
        emit("event_found", events.public(ev))
    _budget(emit, ledger, state["budget"])
    return {"events": found, "cursor": 0, "credits_used": sum(ledger)}


async def context(state: dict, config: RunnableConfig) -> dict:
    emit, as_of = _emit(config), _as_of(state)
    ev = state["events"][state["cursor"]]
    emit("step", {"node": "context", "event_id": ev["id"]})
    ledger = [state["credits_used"]]
    plan = base_pack(ev, as_of)
    envelopes = await asyncio.gather(*(
        _fetch(name, args, run, emit=emit, ledger=ledger, cap=state["budget"])
        for _, name, args, run in plan
    ))
    _budget(emit, ledger, state["budget"])
    pack = {key: env for (key, _, _, _), env in zip(plan, envelopes)}
    return {"work": {"event": ev, "pack": pack, "extra": []}, "credits_used": sum(ledger)}


def _pack_summary(pack: dict) -> dict:
    return {key: {"status": env.get("status"), "error": env.get("error"),
                  "rows": len(findings.rows(env))} for key, env in pack.items()}


async def investigate(state: dict, config: RunnableConfig) -> dict:
    work = state["work"]
    ev = work["event"]
    if ev["kind"] != "right_issue":
        return {}
    emit, as_of = _emit(config), _as_of(state)
    emit("step", {"node": "investigate", "event_id": ev["id"]})
    ledger = [state["credits_used"]]
    messages: list = [
        SystemMessage(content=_INVESTIGATE_PROMPT),
        HumanMessage(content=json.dumps({
            "as_of": state["as_of"],
            "event": events.public(ev),
            "base_pack": _pack_summary(work["pack"]),
            "credits_left": state["budget"] - state["credits_used"],
        }, default=str)),
    ]
    extra: list[dict] = []
    for _ in range(MAX_INVESTIGATE_ROUNDS):
        try:
            ai = await _investigator.ainvoke(messages)
        except Exception:
            logger.warning("aksi investigate: model call failed", exc_info=True)
            break
        messages.append(ai)
        calls = getattr(ai, "tool_calls", None) or []
        if not calls:
            break
        for tc in calls:
            tool = _TOOLS_BY_NAME.get(tc["name"])
            args = _clamp(tc.get("args") or {}, as_of)
            if tool is None:
                envelope = {"error": "tool_not_allowed"}
            else:
                envelope = await _fetch(
                    tool.name, args,
                    lambda tool=tool, args=args: _invoke(tool, args),
                    emit=emit, ledger=ledger, cap=state["budget"])
            extra.append({"tool": tc["name"], "args": args, "envelope": envelope})
            messages.append(ToolMessage(content=json.dumps(envelope, default=str)[:6000],
                                        tool_call_id=tc["id"]))
    _budget(emit, ledger, state["budget"])
    return {"work": {**work, "extra": extra}, "credits_used": sum(ledger)}


async def _invoke(tool: Any, args: dict) -> dict:
    return json.loads(await tool.ainvoke(args))


async def compute(state: dict, config: RunnableConfig) -> dict:
    emit, as_of = _emit(config), _as_of(state)
    work = state["work"]
    ev = work["event"]
    emit("step", {"node": "compute", "event_id": ev["id"]})
    emit("tool", {"name": "aksi_calc", "args": {"symbol": ev["symbol"]}, "status": "call"})
    figures = calc.figures_for(ev, findings.rows(work["pack"].get("prices")), as_of)
    found = findings.extract(ev, work["pack"], work.get("extra", []), as_of)
    emit("tool", {"name": "aksi_calc", "status": "done"})
    emit("numbers", {"event_id": ev["id"], "figures": figures})
    for f in found:
        emit("finding", {"event_id": ev["id"], **f})
    return {"work": {**work, "figures": figures, "findings": found}}


async def brief(state: dict, config: RunnableConfig) -> dict:
    emit = _emit(config)
    work = state["work"]
    ev = work["event"]
    emit("step", {"node": "brief", "event_id": ev["id"]})
    emit("tool", {"name": "aksi_brief", "args": {"symbol": ev["symbol"]}, "status": "call"})
    out = await briefs.produce(ev, work["figures"], work["findings"])
    emit("tool", {"name": "aksi_brief", "status": "done"})
    emit("brief", {"event_id": ev["id"], **out})
    return {"work": {**work, "brief": out}}


async def persist(state: dict, config: RunnableConfig) -> dict:
    work = state["work"]
    result = {"event": events.public(work["event"]), "figures": work["figures"],
              "findings": work["findings"], "brief": work["brief"]}
    await store.append_event(state["report_id"], result, state["credits_used"])
    return {"results": [result], "cursor": state["cursor"] + 1, "work": {}}
```

- [ ] **Step 7: Implement the graph**

```python
# backend/app/aksi/graph.py
"""Aksi Korporasi graph.

START → scan ─(no events)→ END
            └→ context → investigate → compute → brief → persist ─(more)→ context
                                                                  └(done)→ END
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from app.aksi import nodes

RECURSION_LIMIT = 100  # 5 events × 5 nodes + scan exceeds LangGraph's default 25


class AksiState(TypedDict):
    report_id: str
    user_id: int
    mode: str
    as_of: str
    holdings: list[dict]
    events: list[dict]
    cursor: int
    work: dict
    results: Annotated[list[dict], operator.add]
    credits_used: int
    budget: int


def _after_scan(state: AksiState) -> str:
    return "context" if state.get("events") else END


def _after_persist(state: AksiState) -> str:
    return "context" if state["cursor"] < len(state["events"]) else END


def build_aksi_graph() -> StateGraph:
    graph = StateGraph(AksiState)
    for name in ("scan", "context", "investigate", "compute", "brief", "persist"):
        graph.add_node(name, getattr(nodes, name))
    graph.add_edge(START, "scan")
    graph.add_conditional_edges("scan", _after_scan, {"context": "context", END: END})
    graph.add_edge("context", "investigate")
    graph.add_edge("investigate", "compute")
    graph.add_edge("compute", "brief")
    graph.add_edge("brief", "persist")
    graph.add_conditional_edges("persist", _after_persist, {"context": "context", END: END})
    return graph


aksi_graph = build_aksi_graph().compile()
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `docker compose exec backend python -m pytest tests/test_aksi_graph.py -v`
Expected: 3 passed.

- [ ] **Step 9: Commit (after user review)**

```bash
git add backend/app/aksi/sources.py backend/app/aksi/budget.py backend/app/aksi/nodes.py backend/app/aksi/graph.py backend/app/prompts/aksi_investigate.md backend/tests/aksi_fixtures.py backend/tests/test_aksi_graph.py
git commit -m "phase 14g: aksi agent graph"
```

---

### Task 7: Check producer, impact, check/report endpoints

**Files:**
- Create: `backend/app/aksi/service.py`, `backend/app/aksi/impact.py`
- Modify: `backend/app/api/v1/endpoints/aksi.py`
- Test: `backend/tests/test_aksi_check_api.py`

**Interfaces:**
- Consumes: `app.agent.runs.registry/AgentRun/RunLimitError`, `app.api.sse.sse_response`, Tasks 2–6.
- Produces:
  - `service.run_key(user_id) -> str` (`"aksi:{id}"`), `async service.run_check(run, user_id, as_of, symbols, budget_cap) -> None` (never raises)
  - `async impact.impact(symbol, shares, as_of=None) -> dict` (no LLM)
  - Routes: `POST /aksi/check` (SSE), `GET /aksi/check/stream?last_seq=`, `POST /aksi/check/stop`, `GET /aksi/reports/latest?mode=`, `GET /aksi/reports/{id}`, `POST /aksi/impact`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_aksi_check_api.py
"""Check runs over SSE, persisted reports, and the no-LLM impact endpoint."""

import json

import pytest

from app.core.config import settings
from tests import aksi_fixtures as fx

pytestmark = pytest.mark.asyncio


async def _login(client) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.APP_USERNAME, "password": settings.APP_PASSWORD},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _collect(resp) -> list[dict]:
    return [json.loads(line[6:]) async for line in resp.aiter_lines() if line.startswith("data: ")]


async def _check(client, headers, body) -> list[dict]:
    async with client.stream("POST", "/api/v1/aksi/check", json=body, headers=headers) as resp:
        assert resp.status_code == 200
        return await _collect(resp)


async def test_check_streams_and_persists_report(client, monkeypatch):
    fx.install_fakes(monkeypatch)
    h = await _login(client)
    await client.put("/api/v1/aksi/holdings", headers=h, json={"holdings": [
        {"symbol": "WIFI", "shares": 1000}, {"symbol": "BBMD", "shares": 5000}]})

    events = await _check(client, h, {"as_of": fx.AS_OF})
    assert events[0]["type"] == "started" and events[0]["data"]["mode"] == "replay"
    assert events[-1]["type"] == "done" and events[-1]["data"]["events"] == 2
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))

    report = (await client.get("/api/v1/aksi/reports/latest", headers=h)).json()
    assert report["status"] == "done" and report["mode"] == "replay"
    assert len(report["events"]) == 2 and report["credits_spent"] == 9
    same = (await client.get(f"/api/v1/aksi/reports/{report['id']}", headers=h)).json()
    assert same["id"] == report["id"]


async def test_check_without_holdings_finishes_empty(client, monkeypatch):
    fx.install_fakes(monkeypatch)
    h = await _login(client)
    events = await _check(client, h, {"as_of": fx.AS_OF})
    assert [e["type"] for e in events] == ["started", "done"]
    assert events[-1]["data"]["events"] == 0


async def test_impact_returns_figures(client, monkeypatch):
    fx.install_fakes(monkeypatch)
    h = await _login(client)
    resp = await client.post("/api/v1/aksi/impact", headers=h,
                             json={"symbol": "wifi", "shares": 1000, "as_of": fx.AS_OF})
    body = resp.json()
    assert resp.status_code == 200 and body["symbol"] == "WIFI"
    assert body["events"][0]["figures"]["rights_entitled"]["value"] == 1250


async def test_latest_report_404_before_any_check(client):
    h = await _login(client)
    assert (await client.get("/api/v1/aksi/reports/latest", headers=h)).status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend python -m pytest tests/test_aksi_check_api.py -v`
Expected: FAIL (404/405 on `/api/v1/aksi/check`).

- [ ] **Step 3: Implement the producer and impact**

```python
# backend/app/aksi/service.py
"""Aksi check producer — a detached run, like a chat turn.

Keyed `aksi:{user_id}` on the shared run registry: one active check per user,
the same caps, replay buffer and linger eviction as chat.
"""

import asyncio
import logging
import time
from datetime import date

from app.agent.runs import AgentRun, registry
from app.aksi import events, store
from app.aksi.graph import RECURSION_LIMIT, aksi_graph

logger = logging.getLogger(__name__)


def run_key(user_id: int) -> str:
    return f"aksi:{user_id}"


async def run_check(run: AgentRun, user_id: int, as_of: date | None,
                    symbols: list[str] | None, budget_cap: int) -> None:
    """Stream one check into `run`'s buffer. Never raises."""
    report_id: str | None = None
    last: dict = {}
    try:
        holdings = await store.list_holdings(user_id)
        if symbols:
            wanted = set(symbols)
            holdings = [h for h in holdings if h["symbol"] in wanted]
        today = events.today_wib()
        day = as_of or today
        mode = "replay" if day < today else "live"
        report_id = await store.create_report(user_id, mode, day, holdings)
        run.emit("started", {"report_id": report_id, "mode": mode, "as_of": day.isoformat(),
                             "started_at": int(time.time() * 1000)})
        if holdings:
            state = {"report_id": report_id, "user_id": user_id, "mode": mode,
                     "as_of": day.isoformat(), "holdings": holdings, "events": [],
                     "cursor": 0, "work": {}, "results": [], "credits_used": 0,
                     "budget": budget_cap}
            config = {"configurable": {"emit": run.emit}, "recursion_limit": RECURSION_LIMIT}
            async for values in aksi_graph.astream(state, config, stream_mode="values"):
                last = values
        credits = last.get("credits_used", 0)
        await store.finish_report(report_id, "done", credits)
        run.emit("done", {"report_id": report_id, "events": len(last.get("results", [])),
                          "credits_spent": credits})
    except asyncio.CancelledError:
        if report_id:
            await store.finish_report(report_id, "stopped", last.get("credits_used"))
        run.emit("stopped", {"report_id": report_id})
    except Exception:
        logger.exception("aksi check failed for user %s", user_id)
        if report_id:
            await store.finish_report(report_id, "error", last.get("credits_used"))
        run.emit("error", "Check failed.")
    finally:
        registry.finish(run)
```

```python
# backend/app/aksi/impact.py
"""Single-holding impact without an LLM — backs POST /aksi/impact and the
chat agent's `aksi_impact` tool. Same calendar + calculators as the graph."""

from datetime import date, timedelta

from app.aksi import calc, events, findings, sources

NOTE = "Informasi edukatif, bukan rekomendasi investasi."


async def impact(symbol: str, shares: int, as_of: date | None = None) -> dict:
    day = as_of or events.today_wib()
    start, end = events.scan_window(day)
    cal = await sources.calendar(events.KINDS, start, end)
    data = cal.get("data")
    found = events.normalize(data if isinstance(data, dict) else {},
                             [{"symbol": symbol, "shares": shares}], day)
    out = []
    if found:
        prices = await sources.daily_prices(
            symbol, (day - timedelta(days=89)).isoformat(), day.isoformat())
        price_rows = findings.rows(prices)
        out = [{"event": events.public(ev), "figures": calc.figures_for(ev, price_rows, day)}
               for ev in found]
    return {"symbol": symbol, "as_of": day.isoformat(), "events": out,
            "fetched_at": cal.get("fetched_at"), "note": NOTE}
```

- [ ] **Step 4: Add the routes**

Replace `backend/app/api/v1/endpoints/aksi.py` with:

```python
"""Aksi Korporasi: holdings, corporate-action checks (SSE), reports, impact."""

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agent.runs import RunLimitError, registry
from app.aksi import impact as impact_mod
from app.aksi import service, store
from app.api import deps
from app.api.sse import sse_response
from app.models.user import User
from app.schemas.aksi import (
    CheckRequest,
    HoldingsIn,
    HoldingsOut,
    ImpactOut,
    ImpactRequest,
    ReportOut,
)
from app.schemas.chat import StopOut

router = APIRouter()


@router.get("/holdings", response_model=HoldingsOut)
async def get_holdings(current_user: User = Depends(deps.get_current_user)):
    return {"holdings": await store.list_holdings(current_user.id)}


@router.put("/holdings", response_model=HoldingsOut)
async def put_holdings(body: HoldingsIn, current_user: User = Depends(deps.get_current_user)):
    await store.replace_holdings(current_user.id, [h.model_dump() for h in body.holdings])
    return {"holdings": await store.list_holdings(current_user.id)}


@router.post("/check")
async def start_check(body: CheckRequest, current_user: User = Depends(deps.get_current_user)):
    """Start a check — detached like a chat turn; GET /check/stream replays."""
    key = service.run_key(current_user.id)
    async with registry.thread_lock(key):
        await registry.stop_and_wait(key)  # a new check supersedes a live one
        try:
            run = registry.start_run(current_user.id, key)
        except RunLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc))
        run.task = asyncio.create_task(
            service.run_check(run, current_user.id, body.as_of, body.symbols, body.budget)
        )
    return sse_response(run)


@router.get("/check/stream")
async def check_stream(last_seq: int = Query(0, ge=0),
                       current_user: User = Depends(deps.get_current_user)):
    run = registry.get(service.run_key(current_user.id))
    if run is None:
        raise HTTPException(status_code=404, detail="No check for this user")
    return sse_response(run, last_seq)


@router.post("/check/stop", response_model=StopOut)
async def stop_check(current_user: User = Depends(deps.get_current_user)):
    stopped = await registry.stop_and_wait(service.run_key(current_user.id))
    return {"detail": "Stop requested" if stopped else "No active check", "stopped": stopped}


@router.get("/reports/latest", response_model=ReportOut)
async def latest_report(mode: str | None = Query(None, pattern="^(live|replay)$"),
                        current_user: User = Depends(deps.get_current_user)):
    report = await store.latest_report(current_user.id, mode)
    if report is None:
        raise HTTPException(status_code=404, detail="No report yet")
    return report


@router.get("/reports/{report_id}", response_model=ReportOut)
async def get_report(report_id: uuid.UUID, current_user: User = Depends(deps.get_current_user)):
    report = await store.get_report(current_user.id, str(report_id))
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.post("/impact", response_model=ImpactOut)
async def impact(body: ImpactRequest, current_user: User = Depends(deps.get_current_user)):
    return await impact_mod.impact(body.symbol, body.shares, body.as_of)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `docker compose exec backend python -m pytest tests/test_aksi_check_api.py tests/test_aksi_holdings_api.py -v`
Expected: all pass. Then run the full suite: `docker compose exec backend python -m pytest tests` — all pass.

- [ ] **Step 6: Commit (after user review)**

```bash
git add backend/app/aksi/service.py backend/app/aksi/impact.py backend/app/api/v1/endpoints/aksi.py backend/tests/test_aksi_check_api.py
git commit -m "phase 14h: aksi check api + impact"
```

---

### Task 8: Chat integration (P1)

**Files:**
- Create: `backend/app/aksi/tools.py`
- Modify: `backend/app/agent/router.py` (WORKFLOWS), `backend/app/agent/nodes.py` (`_WORKFLOW_HINTS`), `backend/app/agent/tools_node.py` (`AGENT_TOOLS`)
- Test: `backend/tests/test_aksi_tools.py`

**Interfaces:**
- Consumes: `impact.impact`.
- Produces: LangChain tool `aksi_impact(symbol: str, shares: int, as_of: str | None = None) -> str`; workflow key `corporate_actions`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_aksi_tools.py
import json

import pytest
import pytest_asyncio

from app.agent import nodes, router
from app.aksi.tools import aksi_impact
from tests import aksi_fixtures as fx


@pytest_asyncio.fixture
async def _bind(bound_session_maker):
    yield


@pytest.mark.asyncio
async def test_aksi_impact_tool_returns_figures(db, _bind, monkeypatch):
    fx.install_fakes(monkeypatch)
    out = json.loads(await aksi_impact.ainvoke(
        {"symbol": "WIFI", "shares": 1000, "as_of": fx.AS_OF}))
    assert out["events"][0]["figures"]["cost_to_exercise_all"]["value"] == 2500000


@pytest.mark.asyncio
async def test_aksi_impact_rejects_bad_input():
    out = json.loads(await aksi_impact.ainvoke({"symbol": "TOOLONG", "shares": 1}))
    assert out["error"] == "invalid_input"


def test_corporate_actions_workflow_is_registered():
    assert "corporate_actions" in router.WORKFLOWS
    assert "corporate_actions" in nodes._WORKFLOW_HINTS
    assert "aksi_impact" in {t.name for t in nodes.AGENT_TOOLS}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend python -m pytest tests/test_aksi_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: app.aksi.tools`.

- [ ] **Step 3: Implement**

```python
# backend/app/aksi/tools.py
"""`aksi_impact` — corporate-action impact for one holding, for the chat agent.

Deterministic: same calendar + calculators as the Aksi page, no LLM inside.
"""

import json
import re
from datetime import date

from langchain_core.tools import tool

from app.aksi import impact

_SYMBOL = re.compile(r"^[A-Z]{4}$")


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
    sym = symbol.strip().upper().removesuffix(".JK")
    if not _SYMBOL.match(sym) or shares < 1:
        return json.dumps({"error": "invalid_input"})
    try:
        day = date.fromisoformat(as_of) if as_of else None
    except ValueError:
        return json.dumps({"error": "invalid_date"})
    return json.dumps(await impact.impact(sym, shares, day), default=str)
```

In `backend/app/agent/router.py`, add to `WORKFLOWS` (after `deep_research`):

```python
    "corporate_actions": (
        "Questions about what a stock's corporate actions — rights issues "
        "(HMETD), dividends, warrants — mean for the user's own shares: "
        "entitlement, cost, dilution, deadlines."
    ),
```

In `backend/app/agent/nodes.py`, add to `_WORKFLOW_HINTS`:

```python
    "corporate_actions": (
        "The user asks what a corporate action means for their shares. Call "
        "aksi_impact with the ticker and share count (ask for the share count "
        "if missing; 1 lot = 100 shares) and quote its figures and dates — "
        "never compute them yourself. Present neutral scenarios (if exercised / "
        "if sold / if left alone); never advise buying, selling, holding or "
        "exercising. End with: 'Informasi edukatif, bukan rekomendasi investasi.'"
    ),
```

In `backend/app/agent/tools_node.py`:

```python
from app.aksi.tools import aksi_impact
...
AGENT_TOOLS = [*TOOLS, compute, aksi_impact]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec backend python -m pytest tests/test_aksi_tools.py tests/test_agent_nodes.py tests/test_agent_router.py tests/test_agent_tools_node.py -v`
Expected: all pass.

- [ ] **Step 5: Commit (after user review)**

```bash
git add backend/app/aksi/tools.py backend/app/agent/router.py backend/app/agent/nodes.py backend/app/agent/tools_node.py backend/tests/test_aksi_tools.py
git commit -m "phase 14i: corporate-actions chat workflow + aksi_impact tool"
```

---

### Task 9: Frontend types, API client, store, tool labels

**Files:**
- Create: `frontend/lib/aksi.ts`, `frontend/lib/stores/aksi.ts`
- Modify: `frontend/lib/api.ts` (generic SSE + aksi calls), `frontend/lib/tool-labels.ts`

**Interfaces:**
- Consumes: the shared contracts above; `ToolActivity` from `components/agent-status.tsx`; `verbFor`/`detailFor`.
- Produces:
  - Types: `Lang`, `Holding`, `Figure`, `Finding`, `Brief`, `EventKind`, `PublicEvent`, `AksiEvent`, `ReportEvent`, `Report`, `AksiStreamEvent`
  - Helpers: `formatIdr`, `formatPct`, `formatDate`, `formatFigure`, `KIND_LABEL`, `todayIso`
  - API: `getHoldings`, `putHoldings`, `streamAksiCheck`, `stopAksiCheck`, `getLatestReport`
  - Store `useAksiStore` with: `holdings, holdingsLoaded, holdingsVersion, mode, asOf, running, failed, stopped, runStartedAt, durationMs, tools, credits, reportId, reportMode, reportAsOf, events, order, urgentCount, loadHoldings(), saveHoldings(h), setMode(m), setAsOf(d), loadLatest(mode?), refreshBadge(), run(), stop()`

- [ ] **Step 1: Types and formatting**

```ts
// frontend/lib/aksi.ts
/* Aksi Korporasi types + formatting. Shapes come from backend/app/aksi —
   keep in sync. Numbers are only formatted here, never computed. */

export type Lang = "id" | "en";

export type Holding = { symbol: string; shares: number; avg_price?: number | null };

export type FigureUnit = "IDR" | "shares" | "rights" | "ratio" | "days" | "date";

export type Figure = {
  key: string;
  value: number | string | null;
  unit: FigureUnit;
  formula: string;
  inputs: Record<string, unknown>;
  gap: string | null;
};

export type Finding = {
  id: string;
  kind: string;
  text_id: string;
  text_en: string;
  values: Record<string, unknown>;
  source_tool: string;
  fetched_at: string | null;
};

export type Brief = {
  headline_id: string;
  headline_en: string;
  summary_id: string;
  summary_en: string;
  verify_id: string[];
  verify_en: string[];
  context_ids: string[];
  gate: { passed: boolean; reasons: string[]; template: boolean };
};

export type EventKind = "right_issue" | "dividend" | "warrant";

export type PublicEvent = {
  event_id: string;
  symbol: string;
  kind: EventKind;
  phase: string;
  shares: number;
  urgency: number | null;
  row: Record<string, string | number | null>;
};

export type AksiEvent = PublicEvent & {
  figures?: Record<string, Figure>;
  findings: Finding[];
  brief?: Brief;
};

export type ReportEvent = {
  event: PublicEvent;
  figures: Record<string, Figure>;
  findings: Finding[];
  brief: Brief;
};

export type Report = {
  id: string;
  mode: "live" | "replay";
  as_of: string;
  status: string;
  holdings_snapshot: Holding[];
  events: ReportEvent[];
  credits_spent: number;
  created_at: string;
  updated_at: string;
};

export type AksiStreamEvent = {
  seq: number;
  type:
    | "started"
    | "step"
    | "tool"
    | "event_found"
    | "numbers"
    | "finding"
    | "brief"
    | "budget"
    | "done"
    | "stopped"
    | "error";
  data: unknown;
};

export const KIND_LABEL: Record<EventKind, string> = {
  right_issue: "Rights issue (HMETD)",
  dividend: "Dividen tunai",
  warrant: "Waran",
};

const MONTHS: Record<Lang, string[]> = {
  id: ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

function nf(lang: Lang, digits: number) {
  return new Intl.NumberFormat(lang === "id" ? "id-ID" : "en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatIdr(v: number, lang: Lang = "id"): string {
  const abs = Math.abs(v);
  const digits = abs < 1000 && !Number.isInteger(abs) ? 2 : 0;
  return `${v < 0 ? "−" : ""}Rp${nf(lang, digits).format(abs)}`;
}

export function formatPct(ratio: number, lang: Lang = "id"): string {
  return `${nf(lang, 2).format(ratio * 100)}%`;
}

export function formatDate(iso: string, lang: Lang = "id"): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[lang][m - 1]} ${y}`;
}

export function formatFigure(f: Figure | undefined, lang: Lang = "id"): string {
  if (!f || f.value === null || f.value === undefined) return "—";
  switch (f.unit) {
    case "IDR":
      return formatIdr(Number(f.value), lang);
    case "ratio":
      return formatPct(Number(f.value), lang);
    case "date":
      return formatDate(String(f.value), lang);
    case "days":
      return lang === "id" ? `${f.value} hari` : `${f.value} days`;
    default:
      return nf(lang, 0).format(Number(f.value));
  }
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}
```

- [ ] **Step 2: API client** — in `frontend/lib/api.ts`:

1. Add `import type { AksiStreamEvent, Holding, Report } from "@/lib/aksi";` next to the existing `ChartSpec` import.
2. Replace the whole `streamChat` function (from its doc comment to the end of the file) with:

```ts
/** POST an SSE endpoint — yields parsed events until the run finishes. */
async function* streamSSE<E>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<E> {
  const token = getAccessToken();
  const resp = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, err.detail ?? `HTTP ${resp.status}`);
  }
  if (!resp.body) throw new ApiError(0, "No response body");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        for (const line of frame.split("\n")) {
          if (line.startsWith("data: ")) {
            yield JSON.parse(line.slice(6)) as E;
          }
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

/** POST /chat/stream — yields parsed SSE events until the run finishes. */
export function streamChat(
  message: string,
  threadId: string | null,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  return streamSSE<StreamEvent>("/chat/stream", { message, thread_id: threadId }, signal);
}

export const getHoldings = () => apiFetch<{ holdings: Holding[] }>("/aksi/holdings");
export const putHoldings = (holdings: Holding[]) =>
  apiFetch<{ holdings: Holding[] }>("/aksi/holdings", {
    method: "PUT",
    body: JSON.stringify({ holdings }),
  });
export const streamAksiCheck = (
  body: { as_of?: string | null },
  signal?: AbortSignal,
) => streamSSE<AksiStreamEvent>("/aksi/check", body, signal);
export const stopAksiCheck = () =>
  apiFetch<{ stopped: boolean }>("/aksi/check/stop", { method: "POST" });
export const getLatestReport = (mode?: "live" | "replay") =>
  apiFetch<Report>(`/aksi/reports/latest${mode ? `?mode=${mode}` : ""}`);
```

- [ ] **Step 3: Tool labels** — in `frontend/lib/tool-labels.ts` add to `LABELS` (before `compute`):

```ts
  aksi_calc: "Computing your figures",
  aksi_brief: "Writing brief",
  aksi_impact: "Computing corporate-action impact",
```

- [ ] **Step 4: Store**

```ts
// frontend/lib/stores/aksi.ts
"use client";

import { create } from "zustand";
import { toast } from "sonner";

import type { ToolActivity } from "@/components/agent-status";
import type { AksiEvent, Brief, Finding, Holding, PublicEvent, Report } from "@/lib/aksi";
import {
  ApiError,
  getHoldings,
  getLatestReport,
  putHoldings,
  stopAksiCheck,
  streamAksiCheck,
} from "@/lib/api";
import { detailFor, verbFor } from "@/lib/tool-labels";

type Mode = "live" | "replay";

const DEMO_REPLAY_DATE = "2025-07-10"; // WIFI rights-issue window — see the plan's Task 0

interface AksiStore {
  holdings: Holding[];
  holdingsLoaded: boolean;
  /** Bumped on load/save — remounts the editor with fresh initial rows. */
  holdingsVersion: number;
  mode: Mode;
  asOf: string;
  running: boolean;
  failed: boolean;
  stopped: boolean;
  runStartedAt: number | null;
  durationMs?: number;
  tools: ToolActivity[];
  credits: { used: number; budget: number } | null;
  reportId: string | null;
  reportMode: Mode | null;
  reportAsOf: string | null;
  events: Record<string, AksiEvent>;
  order: string[];
  /** Live events whose next deadline is ≤ 7 days away — sidebar badge. */
  urgentCount: number;
  loadHoldings: () => Promise<void>;
  saveHoldings: (holdings: Holding[]) => Promise<boolean>;
  setMode: (mode: Mode) => void;
  setAsOf: (day: string) => void;
  loadLatest: (mode?: Mode) => Promise<void>;
  refreshBadge: () => Promise<void>;
  run: () => void;
  stop: () => void;
}

let controller: AbortController | null = null;

function fromReport(r: Report) {
  const events: Record<string, AksiEvent> = {};
  const order: string[] = [];
  for (const re of r.events) {
    events[re.event.event_id] = { ...re.event, figures: re.figures, findings: re.findings, brief: re.brief };
    order.push(re.event.event_id);
  }
  return { events, order };
}

function countUrgent(events: Record<string, AksiEvent>, order: string[]) {
  return order.filter((id) => {
    const u = events[id]?.urgency;
    return u !== null && u !== undefined && u <= 7;
  }).length;
}

function applyTool(tools: ToolActivity[], d: Record<string, unknown>): ToolActivity[] {
  const name = String(d.name);
  if (d.status === "call") {
    return [
      ...tools,
      { tool: name, label: verbFor(name), detail: detailFor(d.args as Record<string, unknown>), status: "running" },
    ];
  }
  const next = [...tools];
  for (let i = next.length - 1; i >= 0; i--) {
    if (next[i].status === "running" && next[i].tool === name) {
      next[i] = { ...next[i], status: "done" };
      break;
    }
  }
  return next;
}

export const useAksiStore = create<AksiStore>()((set, get) => {
  const patch = (id: unknown, fn: (e: AksiEvent) => Partial<AksiEvent>) =>
    set((s) => {
      const key = String(id);
      const e = s.events[key];
      return e ? { events: { ...s.events, [key]: { ...e, ...fn(e) } } } : {};
    });

  const settle = (status: ToolActivity["status"]) =>
    set((s) => ({
      tools: s.tools.map((t) => (t.status === "running" ? { ...t, status } : t)),
      durationMs: s.runStartedAt ? Date.now() - s.runStartedAt : undefined,
    }));

  return {
    holdings: [],
    holdingsLoaded: false,
    holdingsVersion: 0,
    mode: "live",
    asOf: DEMO_REPLAY_DATE,
    running: false,
    failed: false,
    stopped: false,
    runStartedAt: null,
    tools: [],
    credits: null,
    reportId: null,
    reportMode: null,
    reportAsOf: null,
    events: {},
    order: [],
    urgentCount: 0,

    loadHoldings: async () => {
      try {
        const { holdings } = await getHoldings();
        set((s) => ({ holdings, holdingsLoaded: true, holdingsVersion: s.holdingsVersion + 1 }));
      } catch {
        set({ holdingsLoaded: true });
        toast.error("Gagal memuat portofolio");
      }
    },

    saveHoldings: async (holdings) => {
      try {
        const saved = await putHoldings(holdings);
        set((s) => ({ holdings: saved.holdings, holdingsVersion: s.holdingsVersion + 1 }));
        return true;
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : "Gagal menyimpan portofolio");
        return false;
      }
    },

    setMode: (mode) => {
      if (get().running) return;
      set({ mode });
      void get().loadLatest(mode);
    },

    setAsOf: (day) => set({ asOf: day }),

    loadLatest: async (mode) => {
      try {
        const r = await getLatestReport(mode);
        if (get().running) return;
        const { events, order } = fromReport(r);
        set({
          events,
          order,
          reportId: r.id,
          reportMode: r.mode,
          reportAsOf: r.as_of,
          tools: [],
          credits: null,
          ...(r.mode === "live" ? { urgentCount: countUrgent(events, order) } : {}),
        });
      } catch {
        if (!get().running) set({ events: {}, order: [], reportId: null, reportMode: null, reportAsOf: null });
      }
    },

    refreshBadge: async () => {
      try {
        const r = await getLatestReport("live");
        const { events, order } = fromReport(r);
        set({ urgentCount: countUrgent(events, order) });
      } catch {
        /* no live report yet */
      }
    },

    run: () => {
      if (get().running) return;
      const { mode, asOf } = get();
      const ctrl = new AbortController();
      controller = ctrl;
      set({
        running: true, failed: false, stopped: false, tools: [], credits: null,
        events: {}, order: [], reportId: null, runStartedAt: Date.now(), durationMs: undefined,
      });
      void (async () => {
        try {
          for await (const ev of streamAksiCheck({ as_of: mode === "replay" ? asOf : null }, ctrl.signal)) {
            const d = (ev.data ?? {}) as Record<string, unknown>;
            switch (ev.type) {
              case "started":
                set({
                  reportId: String(d.report_id),
                  reportMode: d.mode as Mode,
                  reportAsOf: String(d.as_of),
                  runStartedAt: Number(d.started_at) || Date.now(),
                });
                break;
              case "tool":
                set((s) => ({ tools: applyTool(s.tools, d) }));
                break;
              case "event_found": {
                const pe = d as unknown as PublicEvent;
                set((s) => ({
                  events: { ...s.events, [pe.event_id]: { ...pe, findings: [] } },
                  order: [...s.order, pe.event_id],
                }));
                break;
              }
              case "numbers":
                patch(d.event_id, () => ({ figures: d.figures as AksiEvent["figures"] }));
                break;
              case "finding":
                patch(d.event_id, (e) => ({ findings: [...e.findings, d as unknown as Finding] }));
                break;
              case "brief":
                patch(d.event_id, () => ({ brief: d as unknown as Brief }));
                break;
              case "budget":
                set({ credits: { used: Number(d.credits_used), budget: Number(d.budget) } });
                break;
              case "done":
                settle("done");
                break;
              case "stopped":
                settle("skipped");
                set({ stopped: true });
                break;
              case "error":
                settle("error");
                set({ failed: true });
                toast.error(String(ev.data));
                break;
            }
          }
        } catch (err) {
          if ((err as Error).name !== "AbortError") {
            settle("error");
            set({ failed: true });
            toast.error(err instanceof ApiError ? err.message : "Pengecekan gagal");
          }
        } finally {
          if (controller === ctrl) controller = null;
          set((s) => ({
            running: false,
            ...(s.reportMode === "live" ? { urgentCount: countUrgent(s.events, s.order) } : {}),
          }));
        }
      })();
    },

    stop: () => {
      stopAksiCheck().catch(() => {});
      settle("skipped");
      set({ stopped: true });
      controller?.abort();
    },
  };
});
```

- [ ] **Step 5: Type-check and lint**

Run: `docker compose exec frontend npx tsc --noEmit && docker compose exec frontend npx eslint .`
Expected: no errors (chat streaming behaves as before; `streamChat` keeps its signature).

- [ ] **Step 6: Commit (after user review)**

```bash
git add frontend/lib/aksi.ts frontend/lib/stores/aksi.ts frontend/lib/api.ts frontend/lib/tool-labels.ts
git commit -m "phase 14j: aksi frontend types, client, store"
```

---

### Task 10: Page, sidebar item, holdings editor, run status

**Files:**
- Create: `frontend/app/(chat)/action/page.tsx`, `frontend/components/aksi/aksi-view.tsx`, `frontend/components/aksi/holdings-editor.tsx`
- Modify: `frontend/components/sidebar-threads.tsx`

**Interfaces:**
- Consumes: `useAksiStore`, `AgentStatus`, shadcn `Button`/`Input`/`SidebarTrigger`/`SidebarMenuBadge`, `EventCard` (Task 11 — render a placeholder `<pre>` until it lands, or implement Task 11 in the same session).
- Produces: route `/action`; `AksiView`; `HoldingsEditor({ initial })`.

- [ ] **Step 1: Read the Next 16 docs** for app-router pages/layouts in `frontend/node_modules/next/dist/docs/` (the route lives in the existing `(chat)` group, so it inherits the auth guard and sidebar).

- [ ] **Step 2: Route**

```tsx
// frontend/app/(chat)/aksi/page.tsx
import { AksiView } from "@/components/aksi/aksi-view";

export default function AksiPage() {
  return <AksiView />;
}
```

- [ ] **Step 3: Holdings editor**

```tsx
// frontend/components/aksi/holdings-editor.tsx
"use client";

import { useState } from "react";
import { PlusIcon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Holding } from "@/lib/aksi";
import { useAksiStore } from "@/lib/stores/aksi";

type Row = { symbol: string; shares: string; avgPrice: string };

const SYMBOL_RE = /^[A-Z]{4}$/;
const BLANK: Row = { symbol: "", shares: "", avgPrice: "" };
const COLS = "grid grid-cols-[6rem_1fr_1fr_2rem] items-center gap-2";

function toRows(holdings: Holding[]): Row[] {
  return holdings.length
    ? holdings.map((h) => ({ symbol: h.symbol, shares: String(h.shares), avgPrice: h.avg_price ? String(h.avg_price) : "" }))
    : [BLANK];
}

function parse(rows: Row[]): { holdings: Holding[]; error: string | null } {
  const holdings = rows
    .filter((r) => r.symbol.trim() || r.shares.trim())
    .map((r) => ({
      symbol: r.symbol.trim().toUpperCase().replace(/\.JK$/, ""),
      shares: Number(r.shares),
      avg_price: r.avgPrice.trim() ? Number(r.avgPrice) : null,
    }));
  if (holdings.some((h) => !SYMBOL_RE.test(h.symbol))) return { holdings, error: "Ticker harus 4 huruf, misalnya BBCA." };
  if (holdings.some((h) => !Number.isInteger(h.shares) || h.shares < 1)) return { holdings, error: "Jumlah saham harus bilangan bulat ≥ 1 (lembar)." };
  if (new Set(holdings.map((h) => h.symbol)).size !== holdings.length) return { holdings, error: "Ticker tidak boleh ganda." };
  return { holdings, error: null };
}

export function HoldingsEditor({ initial }: { initial: Holding[] }) {
  const [rows, setRows] = useState<Row[]>(() => toRows(initial));
  const [saving, setSaving] = useState(false);
  const running = useAksiStore((s) => s.running);
  const { holdings, error } = parse(rows);
  const normalizedInitial = initial.map((h) => ({ symbol: h.symbol, shares: h.shares, avg_price: h.avg_price ?? null }));
  const dirty = JSON.stringify(holdings) !== JSON.stringify(normalizedInitial);

  const update = (i: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const save = async () => {
    setSaving(true);
    const ok = await useAksiStore.getState().saveHoldings(holdings);
    setSaving(false);
    if (ok) toast.success("Portofolio tersimpan");
  };

  return (
    <section className="rounded-xl border border-border bg-card">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-medium tracking-tight">Saham yang kamu pegang</h2>
          <p className="text-xs text-muted-foreground">Jumlah dalam lembar (1 lot = 100 lembar).</p>
        </div>
        <Button size="sm" variant="secondary" disabled={!dirty || !!error || saving || running} onClick={save}>
          {saving ? "Menyimpan…" : "Simpan"}
        </Button>
      </header>
      <div className="space-y-2 px-4 py-3">
        <div className={`${COLS} text-xs text-muted-foreground`}>
          <span>Ticker</span>
          <span>Jumlah (lembar)</span>
          <span>Harga rata-rata (opsional)</span>
          <span />
        </div>
        {rows.map((r, i) => (
          <div key={i} className={COLS}>
            <Input aria-label="Ticker" value={r.symbol} maxLength={7} placeholder="BBCA"
              className="font-mono uppercase" onChange={(e) => update(i, { symbol: e.target.value })} />
            <Input aria-label="Jumlah lembar" inputMode="numeric" value={r.shares} placeholder="1000"
              className="font-mono" onChange={(e) => update(i, { shares: e.target.value.replace(/[^\d]/g, "") })} />
            <Input aria-label="Harga rata-rata" inputMode="decimal" value={r.avgPrice} placeholder="—"
              className="font-mono" onChange={(e) => update(i, { avgPrice: e.target.value.replace(/[^\d.]/g, "") })} />
            <Button size="icon-sm" variant="ghost" aria-label="Hapus baris"
              onClick={() => setRows((rs) => (rs.length > 1 ? rs.filter((_, j) => j !== i) : [BLANK]))}>
              <Trash2Icon className="size-4" />
            </Button>
          </div>
        ))}
        <div className="flex items-center justify-between gap-3">
          <Button size="sm" variant="ghost" disabled={rows.length >= 30} onClick={() => setRows((rs) => [...rs, BLANK])}>
            <PlusIcon className="size-4" />
            Tambah saham
          </Button>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Page shell**

```tsx
// frontend/components/aksi/aksi-view.tsx
"use client";

import { useEffect } from "react";
import { PlayIcon, SquareIcon } from "lucide-react";

import { AgentStatus } from "@/components/agent-status";
import { EventCard } from "@/components/aksi/event-card";
import { HoldingsEditor } from "@/components/aksi/holdings-editor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { formatDate, todayIso } from "@/lib/aksi";
import { useAksiStore } from "@/lib/stores/aksi";
import { cn } from "@/lib/utils";

const DISCLAIMER =
  "Informasi edukatif, bukan rekomendasi investasi. Verifikasi dengan keterbukaan informasi resmi IDX dan prospektus.";

function ModeToggle() {
  const mode = useAksiStore((s) => s.mode);
  const asOf = useAksiStore((s) => s.asOf);
  const running = useAksiStore((s) => s.running);
  return (
    <div className="flex items-center gap-2">
      <div className="flex rounded-md border border-border text-xs" role="group" aria-label="Mode">
        {(["live", "replay"] as const).map((m) => (
          <button key={m} type="button" disabled={running} aria-pressed={mode === m}
            onClick={() => useAksiStore.getState().setMode(m)}
            className={cn("px-2.5 py-1 transition-colors", mode === m ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground")}>
            {m === "live" ? "Hari ini" : "Replay"}
          </button>
        ))}
      </div>
      {mode === "replay" && (
        <Input type="date" aria-label="Tanggal replay" value={asOf} min="2021-01-01" max={todayIso()}
          disabled={running} className="h-7 w-36 font-mono text-xs"
          onChange={(e) => useAksiStore.getState().setAsOf(e.target.value)} />
      )}
    </div>
  );
}

export function AksiView() {
  const holdings = useAksiStore((s) => s.holdings);
  const holdingsLoaded = useAksiStore((s) => s.holdingsLoaded);
  const holdingsVersion = useAksiStore((s) => s.holdingsVersion);
  const running = useAksiStore((s) => s.running);
  const failed = useAksiStore((s) => s.failed);
  const stopped = useAksiStore((s) => s.stopped);
  const tools = useAksiStore((s) => s.tools);
  const credits = useAksiStore((s) => s.credits);
  const durationMs = useAksiStore((s) => s.durationMs);
  const runStartedAt = useAksiStore((s) => s.runStartedAt);
  const reportId = useAksiStore((s) => s.reportId);
  const reportMode = useAksiStore((s) => s.reportMode);
  const reportAsOf = useAksiStore((s) => s.reportAsOf);
  const order = useAksiStore((s) => s.order);
  const events = useAksiStore((s) => s.events);

  useEffect(() => {
    const store = useAksiStore.getState();
    void store.loadHoldings();
    void store.loadLatest(store.mode);
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
        <SidebarTrigger />
        <h1 className="text-sm font-medium tracking-tight">Aksi Korporasi</h1>
        <div className="ml-auto flex items-center gap-2">
          <ModeToggle />
          {running ? (
            <Button size="sm" variant="secondary" onClick={() => useAksiStore.getState().stop()}>
              <SquareIcon className="size-3.5" />
              Stop
            </Button>
          ) : (
            <Button size="sm" disabled={!holdings.length} onClick={() => useAksiStore.getState().run()}>
              <PlayIcon className="size-3.5" />
              Cek aksi korporasi
            </Button>
          )}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6">
          {reportMode === "replay" && reportAsOf && (
            <div className="rounded-lg border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
              Replay historis — data per <span className="font-mono text-foreground">{formatDate(reportAsOf)}</span>. Bukan data hari ini.
            </div>
          )}

          {holdingsLoaded && <HoldingsEditor key={holdingsVersion} initial={holdings} />}

          {(running || tools.length > 0) && (
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <AgentStatus tools={tools} active={running} failed={failed} stopped={stopped}
                  durationMs={durationMs} runStartedAt={runStartedAt} />
              </div>
              {credits && (
                <span className="shrink-0 pt-0.5 font-mono text-xs text-muted-foreground">
                  credits {credits.used}/{credits.budget}
                </span>
              )}
            </div>
          )}

          {order.map((id) => (
            <EventCard key={id} event={events[id]} asOf={reportAsOf} />
          ))}

          {!running && reportId && order.length === 0 && (
            <p className="rounded-xl border border-border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
              Tidak ada aksi korporasi untuk sahammu dalam 30 hari terakhir dan 60 hari ke depan
              {reportAsOf ? ` (per ${formatDate(reportAsOf)})` : ""}.
            </p>
          )}

          <p className="text-xs text-muted-foreground">{DISCLAIMER}</p>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Sidebar item** — in `frontend/components/sidebar-threads.tsx`:
1. Add `CalendarClockIcon` to the `lucide-react` import.
2. Add `SidebarMenuBadge` to the `@/components/ui/sidebar` import.
3. Add `import { useAksiStore } from "@/lib/stores/aksi";`.
4. Inside `SidebarThreads`, next to the existing hooks:

```tsx
  const urgentCount = useAksiStore((s) => s.urgentCount);
  useEffect(() => {
    void useAksiStore.getState().refreshBadge();
  }, []);
```

5. After the `History` `SidebarMenuItem` (inside the same `SidebarMenu`), add:

```tsx
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              tooltip="Aksi Korporasi"
              isActive={pathname === "/action"}
              className="h-10 px-4"
            >
              <Link href="/action">
                <CalendarClockIcon />
                <span className="group-data-[collapsible=icon]:hidden">
                  Aksi Korporasi
                </span>
              </Link>
            </SidebarMenuButton>
            {urgentCount > 0 && (
              <SidebarMenuBadge className="font-mono">{urgentCount}</SidebarMenuBadge>
            )}
          </SidebarMenuItem>
```

- [ ] **Step 6: Verify**

Run: `docker compose exec frontend npx tsc --noEmit && docker compose exec frontend npx eslint .`
Expected: no errors (once Task 11's `event-card.tsx` exists).
Manual: open http://localhost:3000/action → add WIFI 1000 + BBCA 500 → Simpan → reload → rows persist.

- [ ] **Step 7: Commit (after user review)**

```bash
git add "frontend/app/(chat)/action/page.tsx" frontend/components/aksi/aksi-view.tsx frontend/components/aksi/holdings-editor.tsx frontend/components/sidebar-threads.tsx
git commit -m "phase 14k: aksi page, holdings editor, sidebar entry"
```

---

### Task 11: Event card and evidence drawer

**Files:**
- Create: `frontend/components/aksi/event-card.tsx`, `frontend/components/aksi/evidence-drawer.tsx`

**Interfaces:**
- Consumes: `AksiEvent`, formatting helpers, shadcn `Sheet*`, `Button`, `Skeleton`.
- Produces: `EventCard({ event, asOf })`, `EvidenceDrawer({ event })`.

- [ ] **Step 1: Evidence drawer**

```tsx
// frontend/components/aksi/evidence-drawer.tsx
"use client";

import { DatabaseIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { type AksiEvent, formatDate, formatFigure } from "@/lib/aksi";

export function EvidenceDrawer({ event }: { event: AksiEvent }) {
  const figures = Object.values(event.figures ?? {});
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button size="sm" variant="ghost">
          <DatabaseIcon className="size-3.5" />
          Lihat sumber data
        </Button>
      </SheetTrigger>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="font-mono">{event.symbol} · sumber data</SheetTitle>
          <SheetDescription>
            Setiap angka dihitung oleh kode dari data Sectors — bukan oleh AI.
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-6 text-sm">
          <section>
            <h4 className="mb-2 text-xs font-medium text-muted-foreground">Angka & rumus</h4>
            <div className="divide-y divide-border rounded-lg border border-border">
              {figures.map((f) => (
                <div key={f.key} className="space-y-1 px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-xs text-muted-foreground">{f.key}</span>
                    <span className="font-mono">{formatFigure(f)}</span>
                  </div>
                  <div className="font-mono text-[11px] text-muted-foreground">{f.formula}</div>
                  {Object.keys(f.inputs).length > 0 && (
                    <div className="font-mono text-[11px] text-muted-foreground">
                      {JSON.stringify(f.inputs)}
                    </div>
                  )}
                  {f.gap && <div className="text-[11px] text-destructive">{f.gap}</div>}
                </div>
              ))}
            </div>
          </section>
          {event.findings.length > 0 && (
            <section>
              <h4 className="mb-2 text-xs font-medium text-muted-foreground">Konteks</h4>
              <ul className="space-y-2">
                {event.findings.map((f) => (
                  <li key={f.id} className="text-xs">
                    <span className="font-mono text-muted-foreground">{f.source_tool}</span>
                    {f.fetched_at && (
                      <span className="text-muted-foreground"> · diambil {formatDate(f.fetched_at)}</span>
                    )}
                    <div className="mt-0.5 text-ink-muted">{f.text_id}</div>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section>
            <h4 className="mb-2 text-xs font-medium text-muted-foreground">Data mentah aksi korporasi</h4>
            <pre className="overflow-x-auto rounded-lg bg-secondary p-3 font-mono text-[11px]">
              {JSON.stringify(event.row, null, 2)}
            </pre>
          </section>
          <p className="text-xs text-muted-foreground">
            Batasan: data kalender tidak memuat tanggal pengumuman; mode replay hanya memakai data sampai
            tanggal replay; nama pemegang saham utama berasal dari data kepemilikan terkini.
          </p>
        </div>
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 2: Event card**

```tsx
// frontend/components/aksi/event-card.tsx
"use client";

import { useState } from "react";

import { EvidenceDrawer } from "@/components/aksi/evidence-drawer";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type AksiEvent,
  type EventKind,
  type Lang,
  KIND_LABEL,
  formatDate,
  formatFigure,
  formatIdr,
} from "@/lib/aksi";
import { cn } from "@/lib/utils";

const TILES: Record<EventKind, { key: string; label: string }[]> = {
  right_issue: [
    { key: "rights_entitled", label: "HMETD kamu" },
    { key: "cost_to_exercise_all", label: "Dana untuk tebus semua" },
    { key: "terp", label: "TERP (teoretis)" },
    { key: "rights_value_total", label: "Nilai teoretis hak" },
  ],
  dividend: [
    { key: "gross_dividend", label: "Dividen bruto kamu" },
    { key: "yield_on_cost", label: "Yield on cost" },
    { key: "days_to_cum", label: "Menuju tanggal cum" },
  ],
  warrant: [
    { key: "intrinsic_per_warrant", label: "Nilai intrinsik / waran" },
    { key: "days_to_deadline", label: "Menuju batas pelaksanaan" },
  ],
};

const TIMELINE: Record<EventKind, { key: string; label: string }[]> = {
  right_issue: [
    { key: "cum_date", label: "Cum" },
    { key: "ex_date", label: "Ex" },
    { key: "recording_date", label: "Recording" },
    { key: "trading_period_start", label: "Mulai perdagangan HMETD" },
    { key: "trading_period_end", label: "Batas HMETD" },
  ],
  dividend: [
    { key: "cum_date", label: "Cum" },
    { key: "ex_date", label: "Ex" },
    { key: "recording_date", label: "Recording" },
    { key: "payment_date", label: "Pembayaran" },
  ],
  warrant: [
    { key: "trading_period_start", label: "Mulai perdagangan" },
    { key: "ex_per_start", label: "Mulai pelaksanaan" },
    { key: "ex_per_end", label: "Akhir pelaksanaan" },
    { key: "maturity_date", label: "Jatuh tempo" },
  ],
};

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

function Subline({ event }: { event: AksiEvent }) {
  const price = num(event.row.price);
  const amount = num(event.row.dividend_amount);
  const text =
    event.kind === "right_issue"
      ? `Rasio ${event.row.old_ratio ?? "—"} : ${event.row.new_ratio ?? "—"} · Harga pelaksanaan ${price !== null ? formatIdr(price) : "—"}`
      : event.kind === "dividend"
        ? `Dividen per saham ${amount !== null ? formatIdr(amount) : "—"}`
        : `Harga pelaksanaan ${price !== null ? formatIdr(price) : "—"}`;
  return <p className="mt-0.5 text-xs text-muted-foreground">{text}</p>;
}

function Countdown({ days }: { days: number | null }) {
  if (days === null) return null;
  return (
    <span className={cn("shrink-0 rounded-md border px-2 py-0.5 font-mono text-xs",
      days <= 2 ? "border-destructive/50 text-destructive" : "border-border text-muted-foreground")}>
      {days <= 0 ? "hari ini" : `${days} hari lagi`}
    </span>
  );
}

function NumbersGrid({ event }: { event: AksiEvent }) {
  const f = event.figures;
  if (!f) {
    return (
      <div className="grid grid-cols-2 gap-3 px-4 py-3 sm:grid-cols-4">
        {TILES[event.kind].map((t) => <Skeleton key={t.key} className="h-14 rounded-lg" />)}
      </div>
    );
  }
  return (
    <div className="space-y-2 px-4 py-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {TILES[event.kind].map((t) => {
          const fig = f[t.key];
          return (
            <div key={t.key} className="rounded-lg border border-border px-3 py-2"
              title={fig ? `${fig.formula}${fig.gap ? ` — ${fig.gap}` : ""}` : undefined}>
              <div className="text-xs text-muted-foreground">{t.label}</div>
              <div className="mt-1 font-mono text-base text-foreground">{formatFigure(fig)}</div>
            </div>
          );
        })}
      </div>
      {event.kind === "right_issue" && f.dilution_if_ignored?.value != null && (
        <p className="text-xs text-muted-foreground">
          Jika HMETD dibiarkan hangus, porsi kepemilikan turun{" "}
          <span className="font-mono text-foreground">{formatFigure(f.dilution_if_ignored)}</span>.
        </p>
      )}
    </div>
  );
}

function Timeline({ event, asOf }: { event: AksiEvent; asOf: string | null }) {
  const today = asOf ? asOf.slice(0, 10) : null;
  const items = [
    ...TIMELINE[event.kind]
      .map((p) => ({ ...p, date: event.row[p.key] ? String(event.row[p.key]).slice(0, 10) : "", isToday: false }))
      .filter((p) => p.date),
    ...(today ? [{ key: "today", label: "Hari ini", date: today, isToday: true }] : []),
  ].sort((a, b) => a.date.localeCompare(b.date));
  return (
    <ol className="flex gap-5 overflow-x-auto px-4 py-3" aria-label="Linimasa">
      {items.map((p) => (
        <li key={p.key} className="flex min-w-24 flex-col gap-1">
          <span aria-hidden className={cn("size-2 rounded-full",
            p.isToday ? "bg-primary" : today && p.date <= today ? "bg-muted-foreground" : "border border-muted-foreground")} />
          <span className={cn("text-xs", p.isToday ? "text-foreground" : "text-muted-foreground")}>{p.label}</span>
          <span className="font-mono text-xs">{formatDate(p.date)}</span>
        </li>
      ))}
    </ol>
  );
}

function Scenarios({ event }: { event: AksiEvent }) {
  const f = event.figures;
  if (event.kind !== "right_issue" || !f) return null;
  return (
    <div className="space-y-1.5 px-4 py-3 text-sm text-ink-muted">
      <div className="text-xs text-muted-foreground">Tiga skenario (teoretis, sebelum biaya transaksi):</div>
      <p><span className="text-foreground">Ditebus semua:</span> bayar <span className="font-mono">{formatFigure(f.cost_to_exercise_all)}</span>, porsi kepemilikan tetap.</p>
      <p><span className="text-foreground">HMETD dijual:</span> nilai teoretis ±<span className="font-mono">{formatFigure(f.rights_value_total)}</span>, porsi turun <span className="font-mono">{formatFigure(f.dilution_if_ignored)}</span>.</p>
      <p><span className="text-foreground">Dibiarkan:</span> hak hangus setelah <span className="font-mono">{formatFigure(f.deadline)}</span>, nilai teoretis hilang <span className="font-mono">{formatFigure(f.rights_value_total)}</span>.</p>
    </div>
  );
}

function Context({ event, lang }: { event: AksiEvent; lang: Lang }) {
  if (!event.findings.length) return null;
  return (
    <ul className="space-y-2 px-4 py-3">
      {event.findings.map((f) => (
        <li key={f.id} className="text-sm text-ink-muted">
          {lang === "id" ? f.text_id : f.text_en}{" "}
          <span className="ml-1 whitespace-nowrap rounded border border-border px-1 py-0.5 font-mono text-[11px] text-muted-foreground">
            {f.source_tool.replace(/^sectors_/, "")}
            {f.fetched_at ? ` · ${formatDate(f.fetched_at, lang)}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

function BriefBlock({ event, lang, onLang }: { event: AksiEvent; lang: Lang; onLang: (l: Lang) => void }) {
  const b = event.brief;
  if (!b) {
    return (
      <div className="space-y-2 px-4 py-3">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-full" />
      </div>
    );
  }
  const verify = lang === "id" ? b.verify_id : b.verify_en;
  return (
    <div className="space-y-2 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">{lang === "id" ? b.headline_id : b.headline_en}</h3>
        <div className="flex rounded-md border border-border text-xs" role="group" aria-label="Bahasa">
          {(["id", "en"] as const).map((l) => (
            <button key={l} type="button" aria-pressed={lang === l} onClick={() => onLang(l)}
              className={cn("px-2 py-0.5 font-mono uppercase", lang === l ? "bg-secondary text-foreground" : "text-muted-foreground")}>
              {l}
            </button>
          ))}
        </div>
      </div>
      <p className="text-sm leading-6 text-ink-muted">{lang === "id" ? b.summary_id : b.summary_en}</p>
      {verify.length > 0 && (
        <div>
          <div className="text-xs text-muted-foreground">{lang === "id" ? "Yang perlu kamu cek" : "What to verify"}</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink-muted">
            {verify.map((v) => <li key={v}>{v}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export function EventCard({ event, asOf }: { event: AksiEvent; asOf: string | null }) {
  const [lang, setLang] = useState<Lang>("id");
  return (
    <article className="divide-y divide-border rounded-xl border border-border bg-card">
      <header className="flex items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold text-foreground">{event.symbol}</span>
            <span className="text-sm text-muted-foreground">· {KIND_LABEL[event.kind]}</span>
          </div>
          <Subline event={event} />
        </div>
        <Countdown days={event.urgency} />
      </header>
      <NumbersGrid event={event} />
      <Timeline event={event} asOf={asOf} />
      <Scenarios event={event} />
      <Context event={event} lang={lang} />
      <BriefBlock event={event} lang={lang} onLang={setLang} />
      <footer className="flex items-center justify-between gap-3 px-4 py-2">
        <span className="text-xs text-muted-foreground">Informasi edukatif, bukan rekomendasi investasi.</span>
        <EvidenceDrawer event={event} />
      </footer>
    </article>
  );
}
```

- [ ] **Step 3: Verify**

Run: `docker compose exec frontend npx tsc --noEmit && docker compose exec frontend npx eslint . && docker compose exec frontend npm run build`
Expected: no errors; build succeeds.
UI check without the backend check endpoint: temporarily call `useAksiStore.setState({...fromReport(SAMPLE)})` with Appendix A in the browser console or a scratch effect — **never commit the scratch code**.

- [ ] **Step 4: Commit (after user review)**

```bash
git add frontend/components/aksi/event-card.tsx frontend/components/aksi/evidence-drawer.tsx
git commit -m "phase 14l: aksi event cards + evidence drawer"
```

---

### Task 12: End-to-end verification, demo prep, docs

**Files:**
- Modify: `README.md` (feature section + API rows)

- [ ] **Step 1: Full test + checks**

Run: `docker compose exec backend python -m pytest tests` → all pass.
Run: `docker compose exec frontend npx tsc --noEmit && docker compose exec frontend npx eslint . && docker compose exec frontend npm run build` → clean.

- [ ] **Step 2: Live and replay runs (real API — spends credits once, then cached)**
1. `/action` → holdings: WIFI 1000, plus the live symbols found in Task 0 (realistic share counts).
2. Mode **Replay**, date `2025-07-10` (or the date chosen in Task 0) → **Cek aksi korporasi**. Expect the WIFI card: 1.250 HMETD, Rp2.500.000, TERP from the real 2025-07-01 close, −55,56%, deadline 15 Jul 2025, findings with evidence chips, and a brief. Check `credits x/25`.
3. Mode **Hari ini** → run → live events for the Task 0 symbols.
4. Run both again → `/api/v1/sectors/cache/stats` shows hits increasing; a second run costs ~0 credits.
5. Stop mid-run → partial report persists; reload `/action` → the latest report is shown.

- [ ] **Step 3: Copy audit** — grep rendered briefs (`/api/v1/aksi/reports/latest`) for every word in `gate.BANNED`. None may appear. Spot-check three figures by hand against §11 of the spec.

- [ ] **Step 4: README** — add an "Aksi Korporasi (corporate-action copilot)" section under Architecture (2–4 sentences + graph line) and these rows to the API table:

```markdown
| GET/PUT | `/api/v1/aksi/holdings` | user's holdings (scope of checks) |
| POST | `/api/v1/aksi/check` | run a corporate-action check → SSE (`started`/`tool`/`event_found`/`numbers`/`finding`/`brief`/`budget`/`done`) |
| GET | `/api/v1/aksi/check/stream` | re-attach/replay a check (`?last_seq=N`) |
| POST | `/api/v1/aksi/check/stop` | stop the active check (partial report kept) |
| GET | `/api/v1/aksi/reports/latest` | latest report (`?mode=live|replay`) |
| GET | `/api/v1/aksi/reports/{id}` | one report |
| POST | `/api/v1/aksi/impact` | one holding's corporate-action figures, no LLM |
```

- [ ] **Step 5: Commit (after user review)**

```bash
git add README.md
git commit -m "phase 14m: aksi korporasi docs"
```

---

## Appendix A — sample report for frontend development (do not commit as code)

```json
{
  "id": "00000000-0000-0000-0000-000000000001",
  "mode": "replay",
  "as_of": "2025-07-10",
  "status": "done",
  "holdings_snapshot": [{"symbol": "WIFI", "shares": 1000, "avg_price": null}],
  "credits_spent": 9,
  "created_at": "2026-10-07T03:00:00+00:00",
  "updated_at": "2026-10-07T03:00:20+00:00",
  "events": [{
    "event": {"event_id": "WIFI:right_issue:2025-07-02", "symbol": "WIFI", "kind": "right_issue",
      "phase": "window_open", "shares": 1000, "urgency": 5,
      "row": {"symbol": "WIFI.JK", "ex_date": "2025-07-02", "cum_date": "2025-07-01",
        "recording_date": "2025-07-03", "trading_period_start": "2025-07-07",
        "trading_period_end": "2025-07-15", "subscription_date": "2025-07-03",
        "price": 2000, "old_ratio": 4, "new_ratio": 5}},
    "figures": {
      "rights_entitled": {"key": "rights_entitled", "value": 1250, "unit": "rights", "formula": "floor(shares × new_ratio / old_ratio)", "inputs": {"shares": 1000, "new_ratio": 5, "old_ratio": 4}, "gap": null},
      "dilution_if_ignored": {"key": "dilution_if_ignored", "value": 0.555556, "unit": "ratio", "formula": "new_ratio / (old_ratio + new_ratio)", "inputs": {"new_ratio": 5, "old_ratio": 4}, "gap": null},
      "cost_to_exercise_all": {"key": "cost_to_exercise_all", "value": 2500000, "unit": "IDR", "formula": "rights_entitled × price", "inputs": {"rights_entitled": 1250, "price": 2000}, "gap": null},
      "terp": {"key": "terp", "value": 2444.444444, "unit": "IDR", "formula": "(old_ratio × p_cum + new_ratio × price) / (old_ratio + new_ratio)", "inputs": {"old_ratio": 4, "new_ratio": 5, "p_cum": 3000, "price": 2000}, "gap": null},
      "rights_value_total": {"key": "rights_value_total", "value": 555555.555556, "unit": "IDR", "formula": "rights_entitled × right_value", "inputs": {"rights_entitled": 1250, "right_value": 444.444444}, "gap": null},
      "deadline": {"key": "deadline", "value": "2025-07-15", "unit": "date", "formula": "trading_period_end", "inputs": {}, "gap": null},
      "days_to_deadline": {"key": "days_to_deadline", "value": 5, "unit": "days", "formula": "deadline − today (calendar days)", "inputs": {"today": "2025-07-10", "target": "2025-07-15"}, "gap": null}
    },
    "findings": [
      {"id": "controller_change", "kind": "controller_change", "text_id": "PT Investasi Sukses Bersama tercatat membeli saham pada 9 Jul 2025: kepemilikan 40,17% → 42,73%.", "text_en": "PT Investasi Sukses Bersama bought shares on 9 Jul 2025: ownership 40.17% → 42.73%.", "values": {}, "source_tool": "sectors_insider_filings", "fetched_at": "2026-10-07T03:00:05+00:00"},
      {"id": "price_vs_exercise", "kind": "price_vs_exercise", "text_id": "Harga penutupan terakhir Rp2.310 (9 Jul 2025), 15,50% di atas harga pelaksanaan Rp2.000.", "text_en": "Latest close Rp2,310 (9 Jul 2025), 15.50% above the exercise price Rp2,000.", "values": {}, "source_tool": "sectors_daily_prices", "fetched_at": "2026-10-07T03:00:04+00:00"}
    ],
    "brief": {"headline_id": "Rights issue WIFI: 1.250 HMETD untuk posisimu", "headline_en": "WIFI rights issue: 1,250 rights for your position",
      "summary_id": "Dengan 1.000 saham, kamu tercatat berhak atas 1.250 HMETD (rasio 4:5) dengan harga pelaksanaan Rp2.000. Menebus semua hak membutuhkan Rp2.500.000. HMETD dapat diperdagangkan atau dilaksanakan sampai 15 Jul 2025; jika dibiarkan, hak hangus dan porsi kepemilikan turun 55,56%.",
      "summary_en": "With 1,000 shares you are entitled to 1,250 rights (ratio 4:5) at an exercise price of Rp2,000. Exercising all of them costs Rp2,500,000. Rights can be traded or exercised until 15 Jul 2025; if left alone they lapse and your ownership falls by 55.56%.",
      "verify_id": ["Batas waktu internal broker untuk instruksi penebusan"], "verify_en": ["Your broker's internal cut-off for exercise instructions"],
      "context_ids": ["controller_change", "price_vs_exercise"], "gate": {"passed": false, "reasons": [], "template": true}}
  }]
}
```

## Self-review notes (for the plan author)

- Spec coverage: P0 items in spec §8.1 map to Tasks 1–7 and 9–11. P1 chat integration → Task 8. Replay → `as_of` in Tasks 6/7/10. Evidence drawer → Task 11. Persistence → Tasks 2/6/7. Sidebar badge → Tasks 9/10. Spec §8.2 items 2–7 (discuss-in-chat button, "what happened next", free-float chip, split/bonus, paste import, cash-neutral scenario) are deliberately **not** in this plan. Add them only if Task 12 is done with time to spare.
- Type consistency checked: `Figure.to_json` keys ↔ `lib/aksi.ts Figure`; `events.public` ↔ `PublicEvent`; `briefs.produce` output ↔ `Brief`; store `fromReport` ↔ `ReportEvent`; SSE type names ↔ `AksiStreamEvent`.
