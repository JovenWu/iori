"""Deterministic context findings for an event.

Code writes every sentence (with its numbers) — the brief LLM only references
finding ids. Rows dated after `as_of` are ignored so replays never peek ahead.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from app.aksi import calc, fmt

logger = logging.getLogger(__name__)

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
    if holder and not matched:
        # Filings exist but none name the controller — say that rather than
        # pinning someone else's transaction on them.
        return _finding(
            "controller_change",
            f"{holder} tidak tercatat bertransaksi pada periode ini.",
            f"{holder} recorded no transactions in this period.",
            {"holder": holder, "count": 0}, "sectors_insider_filings",
            filings_env)
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
    # Upstream yield is sometimes a ratio (0.05), sometimes percent units
    # (5.0) — values above 1 can only be the latter.
    rendered = fmt.pct_raw(y) if y > 1 else fmt.pct(y)
    rendered_en = fmt.pct_raw(y, "en") if y > 1 else fmt.pct(y, "en")
    return _finding("dividend_yield",
                    f"Yield dividen menurut data Sectors: {rendered}.",
                    f"Dividend yield per Sectors data: {rendered_en}.",
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


def public(f: dict) -> dict:
    """SSE/report shape for a finding."""
    return {k: f.get(k) for k in
            ("id", "kind", "text_id", "text_en", "values", "source_tool", "fetched_at")}


def needs_investigation(found: list[dict]) -> bool:
    """Thin context → let the investigate loop try to pull more (budget permitting)."""
    if not found:
        return True
    return any((f.get("values") or {}).get("count") == 0 for f in found)


def _try(fn, *args) -> dict | None:
    """One malformed row must never sink a finding — or the run."""
    try:
        return fn(*args)
    except Exception:
        logger.warning("aksi finding extractor failed", exc_info=True)
        return None


def extract(ev: dict, pack: dict, extra: list[dict], as_of: date) -> list[dict]:
    kind = ev["kind"]
    if kind == "right_issue":
        candidates = [
            _try(controller_change,
                 _with_extra(pack.get("filings"), extra, "sectors_insider_filings"),
                 pack.get("ownership"), as_of),
            _try(price_vs_exercise, ev,
                 _with_extra(pack.get("prices"), extra, "sectors_daily_prices"), as_of),
            _try(ownership_shift,
                 _with_extra(pack.get("shareholders"), extra, "sectors_shareholders"),
                 as_of),
        ]
    elif kind == "warrant":
        candidates = [
            _try(price_vs_exercise, ev,
                 _with_extra(pack.get("prices"), extra, "sectors_daily_prices"), as_of)
        ]
    elif kind == "dividend":
        candidates = [_try(dividend_yield, ev)]
    else:
        candidates = []
    return [c for c in candidates if c]
