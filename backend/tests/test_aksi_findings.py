from datetime import date

from app.aksi import findings

AS_OF = date(2025, 7, 10)
WIFI = {"price": 2000, "cum_date": "2025-07-01", "trading_period_end": "2025-07-15",
        "old_ratio": 4, "new_ratio": 5}
EV = {"id": "WIFI:right_issue:2025-07-02", "symbol": "WIFI", "kind": "right_issue",
      "row": WIFI, "shares": 1000}


def env(data):
    return {"status": 200, "source": "upstream", "fetched_at": "2025-07-10T17:05:00+07:00", "data": data}


PRICES = env([{"date": "2025-07-01", "close": 3000}, {"date": "2025-07-09", "close": 2310},
              {"date": "2025-07-14", "close": 2100}])
ISB = "PT Investasi Sukses Bersama"
FILINGS = env({"results": [
    {"timestamp": "2025-07-09T10:00:00", "holder_name": ISB, "transaction_type": "buy",
     "share_percentage_before": 40.17, "share_percentage_after": 42.73,
     "amount_transaction": 1480000000, "price": 2000},
    {"timestamp": "2025-06-15T09:00:00", "holder_name": "Budi", "transaction_type": "sell",
     "share_percentage_before": 0.5, "share_percentage_after": 0.4,
     "amount_transaction": 1000000, "price": 2900},
    {"timestamp": "2025-07-14T09:00:00", "holder_name": ISB, "transaction_type": "buy",
     "share_percentage_before": 42.73, "share_percentage_after": 45.0,
     "amount_transaction": 5, "price": 2000},
], "pagination": {}})
OWNERSHIP = env({"symbol": "WIFI.JK", "ownership": {"major_shareholders": [
    {"name": ISB, "share_percentage": 40.17}, {"name": "Masyarakat", "share_percentage": 30.0}]}})
SHARE = env({"symbol": "WIFI.JK", "year": 2025, "data": [
    {"date": "2025-03-31", "shares_number": 1000, "total_f": 100},
    {"date": "2025-04-30", "shares_number": 1000, "total_f": 98},
    {"date": "2025-05-31", "shares_number": 1000, "total_f": 95},
    {"date": "2025-06-30", "shares_number": 1000, "total_f": 90},
    {"date": "2025-07-31", "shares_number": 1000, "total_f": 50},
]})


def test_rows_reads_list_and_nested_results():
    assert len(findings.rows(PRICES)) == 3
    assert len(findings.rows(FILINGS)) == 3
    assert findings.rows({"error": "x"}) == []


def test_top_holder_picks_largest_named_entry():
    assert findings.top_holder(OWNERSHIP) == ISB


def test_controller_change_uses_top_holder_and_ignores_future_rows():
    f = findings.controller_change(FILINGS, OWNERSHIP, AS_OF)
    assert f["values"]["holder"] == ISB and f["values"]["after"] == 42.73
    assert "membeli" in f["text_id"] and "40,17% → 42,73%" in f["text_id"]
    assert "bought" in f["text_en"] and f["source_tool"] == "sectors_insider_filings"


def test_controller_change_without_filings_is_still_a_fact():
    f = findings.controller_change(env({"results": []}), OWNERSHIP, AS_OF)
    assert f["values"]["count"] == 0 and f["text_id"].startswith("Tidak ada")


def test_price_vs_exercise():
    f = findings.price_vs_exercise(EV, PRICES, AS_OF)
    assert f["values"]["close"] == 2310.0 and f["values"]["date"] == "2025-07-09"
    assert "15,50%" in f["text_id"] and "di atas" in f["text_id"]


def test_ownership_shift_until_as_of():
    f = findings.ownership_shift(SHARE, AS_OF)
    assert "turun 1,00 poin" in f["text_id"] and "3 bulan" in f["text_id"]
    assert "10,00% → 9,00%" in f["text_id"]


def test_extract_by_kind():
    pack = {"prices": PRICES, "filings": FILINGS, "ownership": OWNERSHIP, "shareholders": SHARE}
    assert [f["id"] for f in findings.extract(EV, pack, [], AS_OF)] == [
        "controller_change", "price_vs_exercise", "ownership_shift"]
    div = {"kind": "dividend", "row": {"dividend_yield": 0.0168784}}
    out = findings.extract(div, {}, [], AS_OF)
    assert out[0]["id"] == "dividend_yield" and "1,69%" in out[0]["text_id"]
