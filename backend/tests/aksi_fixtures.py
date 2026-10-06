"""Shared upstream fixtures for the Aksi tests — shapes per docs.sectors.app."""

from langchain_core.messages import AIMessage

from app.aksi import briefs, gate, nodes
from app.sectors import client

AS_OF = "2025-07-10"
ISB = "PT Investasi Sukses Bersama"
WIFI_RIGHTS = {"symbol": "WIFI.JK", "ex_date": "2025-07-02", "cum_date": "2025-07-01",
               "recording_date": "2025-07-03", "trading_period_start": "2025-07-07",
               "trading_period_end": "2025-07-15", "subscription_date": "2025-07-03",
               "price": 2000, "old_ratio": 4, "new_ratio": 5}
BBMD_DIVIDEND = {"symbol": "BBMD.JK", "ex_date": "2025-07-14", "cum_date": "2025-07-11",
                 "recording_date": "2025-07-15", "payment_date": "2025-07-25",
                 "dividend_amount": 34.25}
CALENDAR = {"start": "2025-06-10", "end": "2025-09-08", "right_issue": [WIFI_RIGHTS],
            "warrant": [], "upcoming_dividend": [BBMD_DIVIDEND], "dividend": []}
WIFI_PRICES = [{"symbol": "WIFI.JK", "date": "2025-06-30", "close": 2950},
               {"symbol": "WIFI.JK", "date": "2025-07-01", "close": 3000},
               {"symbol": "WIFI.JK", "date": "2025-07-02", "close": 2460},
               {"symbol": "WIFI.JK", "date": "2025-07-09", "close": 2310}]
BBMD_PRICES = [{"symbol": "BBMD.JK", "date": "2025-07-09", "close": 2030}]
OWNERSHIP = {"symbol": "WIFI.JK", "ownership": {"major_shareholders": [
    {"name": ISB, "share_percentage": 40.17}]}}
FILINGS = {"results": [{"symbol": "WIFI.JK", "timestamp": "2025-07-09T10:00:00",
                        "holder_name": ISB, "holder_type": "insider", "transaction_type": "buy",
                        "amount_transaction": 1480000000, "price": 2000,
                        "share_percentage_before": 40.17, "share_percentage_after": 42.73}],
           "pagination": {}}
SHAREHOLDERS = {"symbol": "WIFI.JK", "year": 2025, "data": [
    {"date": "2025-03-31", "shares_number": 2360000000, "total_f": 236000000},
    {"date": "2025-04-30", "shares_number": 2360000000, "total_f": 230000000},
    {"date": "2025-05-31", "shares_number": 2360000000, "total_f": 224000000},
    {"date": "2025-06-30", "shares_number": 2360000000, "total_f": 212400000}]}

ROUTES = {
    "/v2/corporate-actions/": CALENDAR,
    "/v2/daily/WIFI/": WIFI_PRICES,
    "/v2/daily/BBMD/": BBMD_PRICES,
    "/v2/company/report/WIFI/": OWNERSHIP,
    "/v2/filings/": FILINGS,
    "/v2/company/shareholders-composition/WIFI/": SHAREHOLDERS,
}

GOOD_DRAFT = {
    "headline_id": "HMETD {{symbol}}: {{rights_entitled}} hak",
    "headline_en": "{{symbol}} rights: {{rights_entitled}}",
    "summary_id": "Jika ditebus semua, dana yang dibutuhkan {{cost_to_exercise_all}} sampai {{trading_period_end}}.",
    "summary_en": "Exercising all rights needs {{cost_to_exercise_all}} by {{trading_period_end}}.",
    "context_ids": ["controller_change"],
    "verify_id": ["Batas waktu internal broker"],
    "verify_en": ["Your broker's internal cut-off"],
}


def fake_get(calls: list | None = None):
    async def fake(path, params=None):
        if calls is not None:
            calls.append(path)
        if path in ROUTES:
            return 200, ROUTES[path]
        return 404, {"error": "not found"}
    return fake


class FakeWriter:
    async def ainvoke(self, messages, config=None):
        return briefs.BriefDraft(**GOOD_DRAFT)


class FakeInvestigator:
    async def ainvoke(self, messages, config=None):
        return AIMessage(content="enough context")


async def no_jev(state, questions):
    return None


def install_fakes(monkeypatch, calls: list | None = None) -> None:
    monkeypatch.setattr(client, "get", fake_get(calls))
    monkeypatch.setattr(nodes, "_investigator", FakeInvestigator())
    monkeypatch.setattr(briefs, "_writer", FakeWriter())
    monkeypatch.setattr(gate, "jev_ask", no_jev)
