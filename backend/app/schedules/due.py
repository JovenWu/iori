"""Slot math for scheduled jobs — pure functions over WIB wall-clock time."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
# Monthly jobs clamp to the 28th — February never misses a slot.
_MAX_MONTH_DAY = 28


def _slot_on(day: date, run_time: time) -> datetime:
    return datetime.combine(day, run_time, tzinfo=WIB)


def due_now(*, frequency: str, run_time: time, weekday: int | None,
            day_of_month: int | None, last_run_at: datetime | None,
            enabled: bool = True, now: datetime | None = None) -> bool:
    """True when this slot has arrived and hasn't already fired. `last_run_at`
    is stamped at fire time, so a failed/skipped slot never retries."""
    now = now or datetime.now(WIB)
    if not enabled:
        return False
    slot = None
    if frequency == "daily":
        slot = _slot_on(now.date(), run_time)
    elif frequency == "weekly":
        if weekday is not None and now.weekday() == weekday:
            slot = _slot_on(now.date(), run_time)
    elif frequency == "monthly":
        if day_of_month is not None and now.day == day_of_month:
            slot = _slot_on(now.date(), run_time)
    if slot is None or now < slot:
        return False
    return last_run_at is None or last_run_at < slot


def _next_month(now: datetime) -> tuple[int, int]:
    return (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)


def next_run_at(*, frequency: str, run_time: time, weekday: int | None,
                day_of_month: int | None,
                now: datetime | None = None) -> datetime | None:
    """The next future slot in WIB — independent of last_run_at, so a missed
    or manual run still shows the real next occurrence."""
    now = now or datetime.now(WIB)
    if frequency == "daily":
        today = _slot_on(now.date(), run_time)
        return today if now < today else _slot_on(
            now.date() + timedelta(days=1), run_time)
    if frequency == "weekly" and weekday is not None:
        for delta in range(8):
            slot = _slot_on(now.date() + timedelta(days=delta), run_time)
            if slot.weekday() == weekday and now < slot:
                return slot
        return None
    if frequency == "monthly" and day_of_month is not None:
        day = min(day_of_month, _MAX_MONTH_DAY)
        this_month = _slot_on(date(now.year, now.month, day), run_time)
        if now < this_month:
            return this_month
        year, month = _next_month(now)
        return _slot_on(date(year, month, day), run_time)
    return None


def normalize_cadence(frequency: str, weekday: int | None,
                      day_of_month: int | None,
                      ) -> tuple[str, int | None, int | None]:
    """Canonical (frequency, weekday, day_of_month) — irrelevant fields are
    stripped, day_of_month clamps to 28. Raises ValueError on bad input."""
    if frequency == "daily":
        return "daily", None, None
    if frequency == "weekly":
        if weekday is None or not 0 <= weekday <= 6:
            raise ValueError("weekly requires weekday 0-6 (0=Mon)")
        return "weekly", weekday, None
    if frequency == "monthly":
        if day_of_month is None:
            raise ValueError("monthly requires day_of_month")
        return "monthly", None, max(1, min(_MAX_MONTH_DAY, day_of_month))
    raise ValueError("frequency must be daily, weekly or monthly")
