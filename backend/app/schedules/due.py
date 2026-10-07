"""Slot math for scheduled jobs — pure functions over WIB wall-clock time."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
# Monthly jobs clamp to the 28th — February never misses a slot.
_MAX_MONTH_DAY = 28


def _slot_on(day: date, run_time: time) -> datetime:
    return datetime.combine(day, run_time, tzinfo=WIB)


def _weekday_ok(frequency: str, day_weekday: int, weekday: int | None) -> bool:
    # "weekdays" = Mon–Fri — IDX trading days.
    if frequency == "weekdays":
        return day_weekday < 5
    return weekday is not None and day_weekday == weekday


def _prev_month(now: datetime) -> tuple[int, int]:
    return (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)


def _last_slot(*, frequency: str, run_time: time, weekday: int | None,
               day_of_month: int | None,
               now: datetime) -> datetime | None:
    """The most recent slot at or before `now` — checking only today's slot
    silently drops jobs missed while the service was down (server off over a
    Friday slot would wait a whole weekend/month for the next one)."""
    candidates: list[datetime] = []
    if frequency == "daily":
        candidates = [
            _slot_on(now.date(), run_time),
            _slot_on(now.date() - timedelta(days=1), run_time),
        ]
    elif frequency in ("weekly", "weekdays"):
        candidates = [
            _slot_on(now.date() - timedelta(days=d), run_time)
            for d in range(8)
            if _weekday_ok(
                frequency,
                (now.date() - timedelta(days=d)).weekday(),
                weekday,
            )
        ]
    elif frequency == "monthly" and day_of_month is not None:
        day = min(day_of_month, _MAX_MONTH_DAY)
        prev_y, prev_m = _prev_month(now)
        candidates = [
            _slot_on(date(now.year, now.month, day), run_time),
            _slot_on(date(prev_y, prev_m, day), run_time),
        ]
    past = [s for s in candidates if s <= now]
    return max(past) if past else None


def due_now(*, frequency: str, run_time: time, weekday: int | None,
            day_of_month: int | None, last_run_at: datetime | None,
            enabled: bool = True, now: datetime | None = None) -> bool:
    """True when the most recent slot hasn't already fired — a job whose
    slot passed while the service was down catches up on next tick.
    `last_run_at` is stamped at fire/creation time, so a slot never fires
    twice."""
    now = now or datetime.now(WIB)
    if not enabled:
        return False
    slot = _last_slot(frequency=frequency, run_time=run_time,
                      weekday=weekday, day_of_month=day_of_month, now=now)
    if slot is None:
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
    if frequency in ("weekly", "weekdays"):
        for delta in range(8):
            slot = _slot_on(now.date() + timedelta(days=delta), run_time)
            if _weekday_ok(frequency, slot.weekday(), weekday) and now < slot:
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
    if frequency in ("daily", "weekdays"):
        return frequency, None, None
    if frequency == "weekly":
        if weekday is None or not 0 <= weekday <= 6:
            raise ValueError("weekly requires weekday 0-6 (0=Mon)")
        return "weekly", weekday, None
    if frequency == "monthly":
        if day_of_month is None:
            raise ValueError("monthly requires day_of_month")
        return "monthly", None, max(1, min(_MAX_MONTH_DAY, day_of_month))
    raise ValueError("frequency must be daily, weekdays, weekly or monthly")
