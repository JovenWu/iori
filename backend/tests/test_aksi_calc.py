"""Deterministic calculators — the WIFI 2025 rights issue is the oracle."""

from datetime import date
from decimal import Decimal

from app.aksi import calc

WIFI = {
    "symbol": "WIFI.JK", "ex_date": "2025-07-02", "cum_date": "2025-07-01",
    "recording_date": "2025-07-03", "trading_period_start": "2025-07-07",
    "trading_period_end": "2025-07-15", "subscription_date": "2025-07-03",
    "price": 2000, "old_ratio": 4, "new_ratio": 5,
}


def test_rights_issue_wifi_oracle():
    f = calc.rights_issue(1000, WIFI, 3000, 2310, date(2025, 7, 10))
    assert f["rights_entitled"].value == 1250
    assert f["cost_to_exercise_all"].value == Decimal(2_500_000)
    assert abs(f["terp"].value - Decimal("2444.4444")) < Decimal("0.001")
    assert abs(f["rights_value_total"].value - Decimal("555555.56")) < Decimal("0.01")
    assert abs(f["dilution_if_ignored"].value - Decimal("0.5556")) < Decimal("0.0001")
    assert f["deadline"].value == date(2025, 7, 15)
    assert f["days_to_deadline"].value == 5


def test_rights_issue_value_identities():
    f = calc.rights_issue(1000, WIFI, 3000, None, date(2025, 6, 30))
    exercised = f["value_if_exercised"].value
    assert abs(exercised - (Decimal(3_000_000) + f["cost_to_exercise_all"].value)) < Decimal("0.01")
    kept = f["value_if_ignored"].value + f["rights_value_total"].value
    assert abs(kept - Decimal(3_000_000)) < Decimal("0.01")


def test_fractional_rights_are_floored():
    f = calc.rights_issue(1001, WIFI, 3000, None, date(2025, 6, 30))
    assert f["rights_entitled"].value == 1251  # 1001 × 5/4 = 1251.25


def test_missing_price_yields_gaps_not_numbers():
    f = calc.rights_issue(1000, {**WIFI, "price": None}, 3000, None, date(2025, 6, 30))
    assert f["rights_entitled"].value == 1250
    assert f["cost_to_exercise_all"].value is None and f["cost_to_exercise_all"].gap
    assert f["terp"].value is None


def test_right_value_never_negative():
    f = calc.rights_issue(1000, WIFI, 1500, None, date(2025, 6, 30))
    assert f["right_value"].value == 0
    assert f["rights_value_total"].value == 0


def test_dividend_gross_and_days_to_cum():
    row = {"symbol": "BBMD.JK", "ex_date": "2025-07-01", "cum_date": "2025-06-30",
           "recording_date": "2025-07-02", "payment_date": "2025-07-18",
           "dividend_amount": 34.25}
    f = calc.dividend(5000, row, date(2025, 6, 27), avg_price=1900)
    assert f["gross_dividend"].value == Decimal("171250")
    assert f["days_to_cum"].value == 3
    assert abs(f["yield_on_cost"].value - Decimal("0.018026")) < Decimal("0.00001")


def test_warrant_intrinsic_and_deadline():
    row = {"symbol": "ABCD.JK", "trading_period_start": "2025-01-10",
           "ex_per_start": "2025-07-01", "ex_per_end": "2026-01-09",
           "maturity_date": "2026-01-09", "price": 150,
           "ratio_warrant": 1, "ratio_shares": 5}
    f = calc.warrant(1000, row, 180, date(2025, 12, 1))
    assert f["intrinsic_per_warrant"].value == 30
    assert f["days_to_deadline"].value == 39


def test_phase_right_issue():
    assert calc.phase("right_issue", WIFI, date(2025, 6, 30)) == "before_cum"
    assert calc.phase("right_issue", WIFI, date(2025, 7, 3)) == "awaiting_window"
    assert calc.phase("right_issue", WIFI, date(2025, 7, 10)) == "window_open"
    assert calc.phase("right_issue", WIFI, date(2025, 7, 16)) == "expired"


def test_close_lookup_and_figures_for():
    prices = [{"date": "2025-06-30", "close": 2950},
              {"date": "2025-07-01", "close": 3000},
              {"date": "2025-07-09", "close": 2310}]
    assert calc.close_on_or_before(prices, "2025-07-05") == (Decimal(3000), "2025-07-01")
    figs = calc.figures_for({"kind": "right_issue", "row": WIFI, "shares": 1000},
                            prices, date(2025, 7, 10))
    assert figs["rights_entitled"]["value"] == 1250
    assert figs["cost_to_exercise_all"]["value"] == 2500000
    assert round(figs["terp"]["value"], 2) == 2444.44
    assert figs["terp"]["inputs"]["p_cum"] == 3000
    assert figs["deadline"]["value"] == "2025-07-15"
