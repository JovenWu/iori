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
