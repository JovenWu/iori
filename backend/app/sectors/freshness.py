"""Freshness classes for cached Sectors responses.

Cache entries are stored permanently — nothing is evicted on age. Staleness is
computed on read from the entry's freshness class and `fetched_at`, surfaced to
the agent as a hint alongside the current Jakarta time; the agent decides
whether a question needs fresh data (tools take `refresh=True`).

EOD data publishes after the IDX close, so an EOD entry is stale once a weekday
refresh boundary has passed since it was fetched. Date-ranged queries fully in
the past are promoted to HISTORICAL — immutable, never stale.
"""

from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings

WIB = ZoneInfo("Asia/Jakarta")


class Freshness(str, Enum):
    STATIC = "static"  # reference lists — rarely change
    HISTORICAL = "historical"  # date-bounded, fully in the past — immutable
    EOD = "eod"  # daily-updated — refreshes at the weekday EOD boundary
    NEWS = "news"  # may update intraday


def _refresh_time() -> time:
    return time(settings.SECTORS_REFRESH_HOUR_WIB, tzinfo=WIB)


def last_refresh_boundary(now: datetime) -> datetime:
    """Most recent weekday refresh hour (WIB) at or before `now`.

    IDX doesn't trade on weekends, so a boundary landing on Sat/Sun walks back
    to Friday — no new EOD data is published over the weekend.
    """
    now_wib = now.astimezone(WIB)
    candidate = datetime.combine(now_wib.date(), _refresh_time())
    if candidate > now_wib:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def classify(freshness: Freshness, params: dict[str, Any], now: datetime) -> Freshness:
    """Promote EOD queries whose `end` is before today (WIB) to HISTORICAL."""
    if freshness is not Freshness.EOD:
        return freshness
    end = params.get("end")
    try:
        end_date = date.fromisoformat(str(end)) if end else None
    except ValueError:
        end_date = None
    if end_date is not None and end_date < now.astimezone(WIB).date():
        return Freshness.HISTORICAL
    return freshness


def is_stale(freshness: str, fetched_at: datetime, now: datetime) -> bool:
    cls = Freshness(freshness)
    if cls is Freshness.HISTORICAL:
        return False
    if cls is Freshness.STATIC:
        return fetched_at < now - timedelta(days=settings.SECTORS_CACHE_STATIC_DAYS)
    if cls is Freshness.NEWS:
        return fetched_at < now - timedelta(
            minutes=settings.SECTORS_CACHE_NEWS_MINUTES
        )
    return fetched_at < last_refresh_boundary(now)
