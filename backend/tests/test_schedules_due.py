"""Slot math for scheduled jobs — WIB wall-clock, dedup via last_run_at."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.schedules.due import WIB, due_now, next_run_at, normalize_cadence

T1700 = time(17, 0)
# Wednesday 2026-10-07 (weekday() == 2) at 18:00 WIB.
NOW = datetime(2026, 10, 7, 18, 0, tzinfo=ZoneInfo("Asia/Jakarta"))


def _due(**kw):
    kw.setdefault("run_time", T1700)
    kw.setdefault("weekday", None)
    kw.setdefault("day_of_month", None)
    kw.setdefault("last_run_at", None)
    kw.setdefault("now", NOW)
    return due_now(**kw)


def test_daily_due_after_slot():
    assert _due(frequency="daily") is True


def test_daily_not_due_before_slot():
    early = NOW.replace(hour=16, minute=0)
    assert _due(frequency="daily", now=early) is False


def test_daily_not_due_when_already_ran():
    ran = datetime(2026, 10, 7, 17, 5, tzinfo=WIB)
    assert _due(frequency="daily", last_run_at=ran) is False
    # Yesterday's run doesn't block today's slot.
    yesterday = datetime(2026, 10, 6, 17, 5, tzinfo=WIB)
    assert _due(frequency="daily", last_run_at=yesterday) is True


def test_weekly_only_on_matching_weekday():
    assert _due(frequency="weekly", weekday=2) is True   # Wed == Wed
    assert _due(frequency="weekly", weekday=0) is False  # Mon != Wed


def test_weekdays_due_mon_fri_not_weekend():
    assert _due(frequency="weekdays") is True  # Wed
    fri = datetime(2026, 10, 9, 18, 0, tzinfo=WIB)
    assert _due(frequency="weekdays", now=fri) is True
    sat = datetime(2026, 10, 10, 18, 0, tzinfo=WIB)
    assert _due(frequency="weekdays", now=sat) is False
    sun = datetime(2026, 10, 11, 18, 0, tzinfo=WIB)
    assert _due(frequency="weekdays", now=sun) is False


def test_monthly_only_on_day_of_month():
    assert _due(frequency="monthly", day_of_month=7) is True
    assert _due(frequency="monthly", day_of_month=8) is False


def test_disabled_never_due():
    assert _due(frequency="daily", enabled=False) is False


def test_next_run_daily_today_then_tomorrow():
    before = NOW.replace(hour=9)
    nxt = next_run_at(frequency="daily", run_time=T1700, weekday=None,
                      day_of_month=None, now=before)
    assert (nxt.day, nxt.hour) == (7, 17)          # today 17:00
    nxt = next_run_at(frequency="daily", run_time=T1700, weekday=None,
                      day_of_month=None, now=NOW)
    assert (nxt.day, nxt.hour) == (8, 17)          # tomorrow 17:00


def test_next_run_weekly_skips_to_matching_day():
    nxt = next_run_at(frequency="weekly", run_time=T1700, weekday=0,
                      day_of_month=None, now=NOW)  # next Mon
    assert (nxt.day, nxt.weekday(), nxt.hour) == (12, 0, 17)
    # Same-day-but-later still counts.
    before = NOW.replace(hour=9)
    nxt = next_run_at(frequency="weekly", run_time=T1700, weekday=2,
                      day_of_month=None, now=before)
    assert nxt.day == 7


def test_next_run_weekdays_skips_weekend():
    # Friday past the slot → next is Monday.
    fri = datetime(2026, 10, 9, 18, 0, tzinfo=WIB)
    nxt = next_run_at(frequency="weekdays", run_time=T1700, weekday=None,
                      day_of_month=None, now=fri)
    assert (nxt.day, nxt.weekday()) == (12, 0)
    sat = datetime(2026, 10, 10, 9, 0, tzinfo=WIB)
    nxt = next_run_at(frequency="weekdays", run_time=T1700, weekday=None,
                      day_of_month=None, now=sat)
    assert (nxt.day, nxt.weekday()) == (12, 0)
    # A weekday before the slot still lands same-day.
    nxt = next_run_at(frequency="weekdays", run_time=T1700, weekday=None,
                      day_of_month=None, now=NOW.replace(hour=9))
    assert nxt.day == 7


def test_next_run_monthly_this_then_next_month():
    before = NOW.replace(day=1)
    nxt = next_run_at(frequency="monthly", run_time=T1700, weekday=None,
                      day_of_month=7, now=before)
    assert (nxt.month, nxt.day) == (10, 7)
    nxt = next_run_at(frequency="monthly", run_time=T1700, weekday=None,
                      day_of_month=7, now=NOW)
    assert (nxt.month, nxt.day) == (11, 7)


def test_next_run_monthly_clamps_28_in_february():
    feb = datetime(2026, 2, 20, 9, 0, tzinfo=WIB)
    nxt = next_run_at(frequency="monthly", run_time=T1700, weekday=None,
                      day_of_month=31, now=feb)
    assert (nxt.month, nxt.day) == (2, 28)


def test_normalize_cadence():
    assert normalize_cadence("daily", 3, 9) == ("daily", None, None)
    assert normalize_cadence("weekdays", 3, 9) == ("weekdays", None, None)
    assert normalize_cadence("weekly", 4, 9) == ("weekly", 4, None)
    assert normalize_cadence("monthly", 3, 31) == ("monthly", None, 28)
    with pytest.raises(ValueError):
        normalize_cadence("weekly", None, None)
    with pytest.raises(ValueError):
        normalize_cadence("monthly", None, None)
    with pytest.raises(ValueError):
        normalize_cadence("hourly", None, None)
