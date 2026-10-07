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
MAX_EVENTS = 20
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
