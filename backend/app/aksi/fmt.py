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
