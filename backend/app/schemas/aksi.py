import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.aksi.budget import DEFAULT_BUDGET
from app.aksi.events import today_wib

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
    # "Today" is the market's day (WIB), not the server's local date.
    if v is not None and not (_MIN_DATE <= v <= today_wib()):
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
    budget: int = Field(default=DEFAULT_BUDGET, ge=5, le=40)

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
    # True when the calendar read failed — empty `events` is then "unknown",
    # not "nothing pending".
    upstream_error: bool = False
