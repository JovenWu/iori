from datetime import date
from decimal import Decimal

from app.aksi import events, fmt

WIFI = {"symbol": "WIFI.JK", "ex_date": "2025-07-02", "cum_date": "2025-07-01",
        "recording_date": "2025-07-03", "trading_period_start": "2025-07-07",
        "trading_period_end": "2025-07-15", "subscription_date": "2025-07-03",
        "price": 2000, "old_ratio": 4, "new_ratio": 5}
BBMD = {"symbol": "BBMD.JK", "ex_date": "2025-07-14", "cum_date": "2025-07-11",
        "recording_date": "2025-07-15", "payment_date": "2025-07-25",
        "dividend_amount": 34.25}
CAL = {"right_issue": [WIFI, {**WIFI, "symbol": "ZZZZ.JK"}],
       "upcoming_dividend": [BBMD], "dividend": [BBMD], "warrant": []}
HOLD = [{"symbol": "WIFI", "shares": 1000}, {"symbol": "BBMD", "shares": 5000, "avg_price": 1900}]


def test_scan_window_spans_90_days():
    assert events.scan_window(date(2025, 7, 10)) == ("2025-06-10", "2025-09-08")


def test_normalize_filters_dedupes_and_orders_by_urgency():
    evs = events.normalize(CAL, HOLD, date(2025, 7, 10))
    assert [e["id"] for e in evs] == ["BBMD:dividend:2025-07-14", "WIFI:right_issue:2025-07-02"]
    assert (evs[0]["urgency"], evs[0]["phase"]) == (1, "before_cum")
    assert (evs[1]["urgency"], evs[1]["phase"]) == (5, "window_open")
    assert evs[0]["avg_price"] == 1900 and evs[1]["shares"] == 1000


def test_finished_events_are_dropped():
    assert events.normalize(CAL, HOLD, date(2025, 7, 30)) == []


def test_cap_at_max_events():
    symbols = [f"T{i:02d}" for i in range(events.MAX_EVENTS + 1)]
    cal = {"upcoming_dividend": [{**BBMD, "symbol": f"{s}.JK"} for s in symbols]}
    hold = [{"symbol": s, "shares": 100} for s in symbols]
    assert len(events.normalize(cal, hold, date(2025, 7, 10))) == events.MAX_EVENTS


def test_public_shape():
    ev = events.normalize(CAL, HOLD, date(2025, 7, 10))[1]
    pub = events.public(ev)
    assert pub["event_id"] == ev["id"] and pub["row"]["price"] == 2000
    assert set(pub) == {"event_id", "symbol", "kind", "phase", "shares", "urgency", "row"}


def test_formatting():
    assert fmt.idr(2500000) == "Rp2.500.000"
    assert fmt.idr(2500000, "en") == "Rp2,500,000"
    assert fmt.idr(Decimal("34.25")) == "Rp34,25"
    assert fmt.idr(Decimal("2444.4444")) == "Rp2.444"
    assert fmt.pct(Decimal(5) / Decimal(9)) == "55,56%"
    assert fmt.pct(Decimal(5) / Decimal(9), "en") == "55.56%"
    assert fmt.pct_raw(40.17) == "40,17%"
    assert fmt.points(Decimal("0.01")) == "1,00"
    assert fmt.day("2025-07-15") == "15 Jul 2025"
    assert fmt.day("2025-08-01") == "1 Agu 2025"
    assert fmt.figure({"value": 1250, "unit": "rights"}) == "1.250"
    assert fmt.figure({"value": 5, "unit": "days"}) == "5 hari"
    assert fmt.figure({"value": None, "unit": "IDR"}) == "—"
