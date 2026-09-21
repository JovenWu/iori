"""Freshness math: refresh boundary (weekday 17:00 WIB), EOD→HISTORICAL
promotion, and per-class staleness."""

from datetime import datetime, timedelta, timezone

from app.sectors.freshness import (
    Freshness,
    classify,
    is_stale,
    last_refresh_boundary,
)

UTC = timezone.utc


def _utc(y, m, d, hh):
    """Express a WIB wall-clock time as a UTC datetime (WIB = UTC+7)."""
    return datetime(y, m, d, hh - 7, tzinfo=UTC)


def test_boundary_weekday_before_close():
    # Wed 2026-07-08 10:00 WIB → last boundary was Tue 17:00 WIB.
    now = _utc(2026, 7, 8, 10)
    assert last_refresh_boundary(now) == _utc(2026, 7, 7, 17)


def test_boundary_weekday_after_close():
    # Wed 2026-07-08 18:00 WIB → boundary passed today.
    now = _utc(2026, 7, 8, 18)
    assert last_refresh_boundary(now) == _utc(2026, 7, 8, 17)


def test_boundary_skips_weekend():
    # Sun 12:00 WIB and Sat 18:00 WIB → last real boundary is Fri 17:00.
    fri = _utc(2026, 7, 10, 17)
    assert last_refresh_boundary(_utc(2026, 7, 12, 12)) == fri
    assert last_refresh_boundary(_utc(2026, 7, 11, 18)) == fri


def test_classify_promotes_past_end():
    now = _utc(2026, 7, 8, 12)  # today WIB = 2026-07-08
    assert classify(Freshness.EOD, {"end": "2026-07-07"}, now) is Freshness.HISTORICAL


def test_classify_keeps_eod_for_today_or_missing_end():
    now = _utc(2026, 7, 8, 12)
    assert classify(Freshness.EOD, {"end": "2026-07-08"}, now) is Freshness.EOD
    assert classify(Freshness.EOD, {}, now) is Freshness.EOD
    assert classify(Freshness.EOD, {"end": "not-a-date"}, now) is Freshness.EOD


def test_classify_non_eod_unchanged():
    now = _utc(2026, 7, 8, 12)
    assert classify(Freshness.STATIC, {"end": "2020-01-01"}, now) is Freshness.STATIC
    assert classify(Freshness.NEWS, {"end": "2020-01-01"}, now) is Freshness.NEWS


def test_is_stale_historical_never():
    old = datetime(2020, 1, 1, tzinfo=UTC)
    assert not is_stale("historical", old, datetime(2026, 7, 8, tzinfo=UTC))


def test_is_stale_eod_around_boundary():
    # Fetched Wed 10:00 WIB; boundary Wed 17:00 WIB passes → stale.
    fetched = _utc(2026, 7, 8, 10)
    assert is_stale("eod", fetched, _utc(2026, 7, 8, 18))
    # Fetched after Wed's boundary; Thu morning → still fresh.
    fetched = _utc(2026, 7, 8, 18)
    assert not is_stale("eod", fetched, _utc(2026, 7, 9, 10))


def test_is_stale_static_and_news():
    now = datetime(2026, 7, 8, tzinfo=UTC)
    assert is_stale("static", now - timedelta(days=8), now)
    assert not is_stale("static", now - timedelta(days=6), now)
    assert is_stale("news", now - timedelta(minutes=40), now)
    assert not is_stale("news", now - timedelta(minutes=10), now)
