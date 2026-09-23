"""Chart detection: JEV gate + view pick, deterministic extractors."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.sectors import charts

pytestmark = pytest.mark.asyncio


def _envelope(data, status=200, **extra):
    return json.dumps(
        {"status": status, "source": "upstream", "stale": False,
         "fetched_at": "2026-09-21T17:00:00", "data": data, **extra}
    )


def _resp(noul=1.0, view="price_volume"):
    return SimpleNamespace(
        nouls={"chartable": SimpleNamespace(noul=noul)},
        choices={"view": SimpleNamespace(choice=view)},
    )


def _view(view, noul=1.0):
    """Factory: async jev_ask fake that approves and picks `view`."""
    async def fake(state, questions):
        return _resp(noul=noul, view=view)
    return fake


DAILY = [
    {"symbol": "BBCA.JK", "date": "2026-09-17", "close": 6200,
     "open": 6175, "high": 6250, "low": 6150, "volume": 9000000,
     "market_cap": 7.5e14},
    {"symbol": "BBCA.JK", "date": "2026-09-18", "close": 6175,
     "open": 6200, "high": 6225, "low": 6100, "volume": 11000000,
     "market_cap": 7.4e14},
    {"symbol": "BBCA.JK", "date": "2026-09-21", "close": 6300,
     "open": 6180, "high": 6325, "low": 6150, "volume": 12000000,
     "market_cap": 7.6e14},
]


async def test_judge_builds_price_volume_spec(monkeypatch):
    async def fake_ask(state, questions):
        assert "chartable" in questions and "view" in questions
        assert "none" in questions["view"].criteria
        return _resp(view="price_volume")

    monkeypatch.setattr(charts, "jev_ask", fake_ask)
    spec = await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(DAILY), "harga BBCA sebulan"
    )
    assert spec is not None
    assert spec["view"] == "price_volume" and spec["kind"] == "price_volume"
    assert spec["tool"] == "sectors_daily_prices"
    assert spec["x"] == {"key": "date", "label": "Date", "type": "time"}
    assert [p["close"] for p in spec["data"]] == [6200, 6175, 6300]
    assert spec["fetched_at"] == "2026-09-21T17:00:00"


async def test_non_sectors_tool_never_calls_jev(monkeypatch):
    async def boom(state, questions):
        raise AssertionError("jev_ask must not run for non-sectors tools")

    monkeypatch.setattr(charts, "jev_ask", boom)
    assert await charts.judge_and_extract(
        "compute", _envelope({"result": 42}), "x"
    ) is None


GENERIC_ROWS = [
    {"date": "2026-09-19", "free_float": 0.41},
    {"date": "2026-09-20", "free_float": 0.42},
    {"date": "2026-09-21", "free_float": 0.44},
]


async def test_generic_view_charts_unregistered_tool(monkeypatch):
    """A sectors_* tool with no registered view still charts when JEV picks
    generic — percent-shaped fields get percent formatting."""
    monkeypatch.setattr(charts, "jev_ask", _view("generic"))
    spec = await charts.judge_and_extract(
        "sectors_free_float", _envelope(GENERIC_ROWS), "free float trend"
    )
    assert spec is not None
    assert spec["kind"] == "line" and spec["format"] == "percent"
    assert spec["series"][0]["key"] == "free_float"


async def test_generic_rows_without_numbers_returns_none(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("generic"))
    news = [{"title": "BBCA buyback", "published": "2026-09-21"},
            {"title": "BBRI dividend", "published": "2026-09-22"}]
    assert await charts.judge_and_extract(
        "sectors_news", _envelope(news), "news terbaru"
    ) is None


async def test_generic_symbol_map_picks_preferred_field(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("generic"))
    spec = await charts.judge_and_extract(
        "sectors_broker_activity", _envelope(FLOW_MULTI), "bandingkan flow"
    )
    assert spec is not None and spec["kind"] == "line"
    assert {s["key"] for s in spec["series"]} == {"BBCA", "BBRI"}
    assert spec["data"][0]["BBCA"] == 1.4e11  # net_foreign_inflow won


async def test_generic_scalar_dict_bars(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("generic"))
    spec = await charts.judge_and_extract(
        "sectors_index_universe",
        _envelope({"IDX30": 512.3, "LQ45": 890.1, "KOMPAS100": 1200.5}),
        "index board",
    )
    assert spec is not None and spec["kind"] == "bar"


async def test_named_view_failure_falls_back_to_generic(monkeypatch):
    """JEV picks a named view that can't shape the data → generic rescues."""
    monkeypatch.setattr(charts, "jev_ask", _view("quarterly_grouped"))
    rows = [{"date": "2026-06-30", "eps": 120},
            {"date": "2026-09-30", "eps": 150}]
    spec = await charts.judge_and_extract(
        "sectors_quarterly_financials", _envelope(rows), "eps trend"
    )
    assert spec is not None
    assert spec["kind"] == "line" and spec["view"] == "generic"


async def test_truncated_structured_envelope_still_charts(monkeypatch):
    """Row-trimmed data (truncated=True but still a list/dict) is chartable —
    only string-destroyed data should skip."""
    monkeypatch.setattr(charts, "jev_ask", _view("netflow"))
    spec = await charts.judge_and_extract(
        "sectors_foreign_flow",
        _envelope(FOREIGN_FLOW, truncated=True),
        "foreign flow BBCA",
    )
    assert spec is not None and spec["kind"] == "signed_area"


async def test_bad_envelopes_skip(monkeypatch):
    async def boom(state, questions):
        raise AssertionError("must skip before JEV")

    monkeypatch.setattr(charts, "jev_ask", boom)
    assert await charts.judge_and_extract(
        "sectors_daily_prices", '{"error": "sectors_api_unavailable"}', "x"
    ) is None
    assert await charts.judge_and_extract(
        "sectors_daily_prices", "not json", "x"
    ) is None
    # Row-trimmed envelopes still chart — only string-destroyed data skips.
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope("…cut off", truncated=True), "x"
    ) is None
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope({"error": "nf"}, status=404), "x"
    ) is None


async def test_jev_none_or_low_noul_or_none_view(monkeypatch):
    async def unavailable(state, questions):
        return None

    monkeypatch.setattr(charts, "jev_ask", unavailable)
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(DAILY), "x"
    ) is None

    async def low(state, questions):
        return _resp(noul=0.2)

    monkeypatch.setattr(charts, "jev_ask", low)
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(DAILY), "x"
    ) is None

    async def none_view(state, questions):
        return _resp(view="none")

    monkeypatch.setattr(charts, "jev_ask", none_view)
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(DAILY), "x"
    ) is None


IDX_TOTAL = [
    {"date": "2026-09-17", "idx_total_market_cap": 1.0e16},
    {"date": "2026-09-18", "idx_total_market_cap": 1.01e16},
    {"date": "2026-09-21", "idx_total_market_cap": 1.02e16},
]

FOREIGN_FLOW = {
    "symbol": "BBCA.JK", "start": "2026-09-15", "end": "2026-09-21",
    "data": [
        {"date": "2026-09-17", "net_foreign_inflow": 1.4e11,
         "foreign_buy_idr": 5.5e11, "foreign_sell_idr": 4.1e11,
         "foreign_share": 0.58},
        {"date": "2026-09-18", "net_foreign_inflow": -2.0e10,
         "foreign_buy_idr": 4.0e11, "foreign_sell_idr": 4.2e11,
         "foreign_share": 0.51},
        {"date": "2026-09-21", "net_foreign_inflow": 3.0e10,
         "foreign_buy_idr": 6.0e11, "foreign_sell_idr": 5.7e11,
         "foreign_share": 0.55},
    ],
}

QUARTERLY = [
    {"symbol": "BBCA.JK", "date": "2026-03-31", "revenue": 2.8e13,
     "earnings": 1.47e13},
    {"symbol": "BBCA.JK", "date": "2026-06-30", "revenue": 2.9e13,
     "earnings": 1.5e13},
    {"symbol": "BBCA.JK", "date": "2026-09-30", "revenue": 3.0e13,
     "earnings": 1.6e13},
]

LISTING_PERF = {
    "symbol": "BREN.JK", "company_name": "PT Barito Renewables Energy Tbk.",
    "chg_7d": 2.53, "chg_30d": 4.64, "chg_90d": 8.26, "chg_365d": 7.59,
    "offering_price": 780, "listing_date": "2023-10-09",
}


async def test_mcap_area(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("mcap_area"))
    spec = await charts.judge_and_extract(
        "sectors_idx_market_summary", _envelope(IDX_TOTAL), "total mcap"
    )
    assert spec["kind"] == "area" and spec["format"] == "idr"
    assert spec["data"][0]["mcap"] == 1.0e16


async def test_netflow_signed_area(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("netflow"))
    spec = await charts.judge_and_extract(
        "sectors_foreign_flow", _envelope(FOREIGN_FLOW), "foreign flow BBCA"
    )
    assert spec["kind"] == "signed_area" and spec["format"] == "idr"
    assert [p["net"] for p in spec["data"]] == [1.4e11, -2.0e10, 3.0e10]


FOREIGN_FLOW_B = {
    "symbol": "BBRI.JK", "start": "2026-09-15", "end": "2026-09-21",
    "data": [
        {"date": "2026-09-17", "net_foreign_inflow": -5.0e10},
        {"date": "2026-09-18", "net_foreign_inflow": 2.0e10},
        {"date": "2026-09-21", "net_foreign_inflow": 8.0e10},
    ],
}

# Multi-symbol fan-out shape: {SYM: sub-envelope}.
FLOW_MULTI = {
    "BBCA": {"status": 200, "source": "upstream", "stale": False,
             "fetched_at": "2026-09-21T17:00:00", "data": FOREIGN_FLOW},
    "BBRI": {"status": 200, "source": "upstream", "stale": False,
             "fetched_at": "2026-09-21T17:00:00", "data": FOREIGN_FLOW_B},
}

DAILY_B = [
    {"symbol": "BBRI.JK", "date": "2026-09-17", "close": 4000,
     "volume": 50000000},
    {"symbol": "BBRI.JK", "date": "2026-09-18", "close": 4200,
     "volume": 55000000},
    {"symbol": "BBRI.JK", "date": "2026-09-21", "close": 3900,
     "volume": 60000000},
]

PRICE_MULTI = {
    "BBCA": {"status": 200, "source": "upstream", "stale": False,
             "fetched_at": "2026-09-21T17:00:00", "data": DAILY},
    "BBRI": {"status": 200, "source": "upstream", "stale": False,
             "fetched_at": "2026-09-21T17:00:00", "data": DAILY_B},
}


async def test_netflow_multi_symbol_lines(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("netflow"))
    spec = await charts.judge_and_extract(
        "sectors_foreign_flow", _envelope(FLOW_MULTI), "arus asing BBCA vs BBRI"
    )
    assert spec["kind"] == "line" and spec["format"] == "idr"
    assert {s["key"] for s in spec["series"]} == {"BBCA", "BBRI"}
    first = spec["data"][0]
    assert first["date"] == "2026-09-17"
    assert first["BBCA"] == 1.4e11 and first["BBRI"] == -5.0e10


async def test_price_volume_multi_symbol_indexed_lines(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("price_volume"))
    spec = await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(PRICE_MULTI), "harga BBCA vs BBRI"
    )
    assert spec["kind"] == "line"
    assert {s["key"] for s in spec["series"]} == {"BBCA", "BBRI"}
    first, last = spec["data"][0], spec["data"][-1]
    assert first["BBCA"] == 100.0 and first["BBRI"] == 100.0  # rebased
    assert last["BBRI"] == pytest.approx(97.5)  # 3900/4000
    assert last["BBCA"] == pytest.approx(6300 / 6200 * 100, abs=0.01)


async def test_quarterly_grouped_bars(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("quarterly_grouped"))
    spec = await charts.judge_and_extract(
        "sectors_quarterly_financials", _envelope(QUARTERLY), "BBCA quarters"
    )
    assert spec["kind"] == "grouped_bar"
    assert {s["key"] for s in spec["series"]} == {"revenue", "earnings"}


QUARTERLY_B = [
    {"symbol": "BBRI.JK", "date": "2026-03-31", "revenue": 3.5e13,
     "earnings": 1.8e13},
    {"symbol": "BBRI.JK", "date": "2026-06-30", "revenue": 3.7e13,
     "earnings": 1.9e13},
]

Q_MULTI = {
    "BBCA": {"status": 200, "source": "upstream", "stale": False,
             "fetched_at": "2026-09-23T14:48:00", "data": QUARTERLY},
    "BBRI": {"status": 200, "source": "upstream", "stale": False,
             "fetched_at": "2026-09-23T14:48:00", "data": QUARTERLY_B},
}


async def test_quarterly_multi_symbol_lines(monkeypatch):
    """Multi-symbol quarterly fan-out → revenue+earnings line per ticker on
    one shared quarter axis, instead of one chart per bank."""
    monkeypatch.setattr(charts, "jev_ask", _view("quarterly_grouped"))
    spec = await charts.judge_and_extract(
        "sectors_quarterly_financials", _envelope(Q_MULTI), "bandingkan BBCA BBRI"
    )
    assert spec["kind"] == "line" and spec["format"] == "idr"
    keys = {s["key"] for s in spec["series"]}
    assert keys == {"BBCA revenue", "BBCA earnings",
                    "BBRI revenue", "BBRI earnings"}
    first = spec["data"][0]
    assert first["date"] == "2026-03-31"
    assert first["BBCA revenue"] == 2.8e13 and first["BBRI revenue"] == 3.5e13


async def test_listing_perf_bars(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("perf_bars"))
    spec = await charts.judge_and_extract(
        "sectors_listing_performance", _envelope(LISTING_PERF), "BREN ipo"
    )
    assert spec["kind"] == "bar" and spec["format"] == "percent_raw"
    assert [p["window"] for p in spec["data"]] == ["7d", "30d", "90d", "365d"]


async def test_too_few_points_returns_none(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("price_volume"))
    assert await charts.judge_and_extract(
        "sectors_daily_prices", _envelope(DAILY[:1]), "x"
    ) is None


TOP_MOVERS = {
    "top_gainers": {
        "1d": [
            {"name": "PT Nitrasanata Dharma Tbk", "symbol": "JECX.JK",
             "price_change": 0.25, "last_close_price": 1950,
             "latest_close_date": "2026-09-18"},
            {"name": "PT Samator Indo Gas Tbk", "symbol": "AGII.JK",
             "price_change": 0.12, "last_close_price": 2200,
             "latest_close_date": "2026-09-18"},
        ]
    },
    "top_losers": {
        "1d": [
            {"name": "PT Contoh Tbk", "symbol": "CNTO.JK",
             "price_change": -0.18, "last_close_price": 900,
             "latest_close_date": "2026-09-18"},
            {"name": "PT Turun Tbk", "symbol": "TRUN.JK",
             "price_change": -0.11, "last_close_price": 500,
             "latest_close_date": "2026-09-18"},
        ]
    },
}

MOST_TRADED = {
    "2026-09-18": [
        {"symbol": "GOTO.JK", "company_name": "PT GoTo", "volume": 2.6e9,
         "price": 82},
        {"symbol": "DEWA.JK", "company_name": "Darma Henwa", "volume": 1.5e9,
         "price": 138},
    ],
    "2026-09-21": [
        {"symbol": "GOTO.JK", "company_name": "PT GoTo", "volume": 3.0e9,
         "price": 84},
        {"symbol": "BRMS.JK", "company_name": "Bumi Resources", "volume": 2.1e9,
         "price": 190},
    ],
    "2026-09-22": [
        {"symbol": "GOTO.JK", "company_name": "PT GoTo", "volume": 1.0e9,
         "price": 85},
        {"symbol": "DEWA.JK", "company_name": "Darma Henwa", "volume": 1.2e9,
         "price": 140},
    ],
}

BROKER_SUMMARY = {
    "symbol": "BBCA.JK", "start": "2026-09-08", "end": "2026-09-21",
    "data": [
        {"date": "2026-09-18",
         "summary": [
             {"broker_code": "KZ", "bval": 1.1e12, "sval": 5.0e11,
              "nval": 6.0e11, "nlot": 100, "bfreq": 5, "sfreq": 3,
              "blot": 120, "slot": 20},
             {"broker_code": "BK", "bval": 5.0e11, "sval": 8.0e11,
              "nval": -3.0e11, "nlot": -30, "bfreq": 4, "sfreq": 6,
              "blot": 50, "slot": 80},
         ]},
        {"date": "2026-09-21",
         "summary": [
             {"broker_code": "KZ", "bval": 5.0e11, "sval": 1.0e11,
              "nval": 4.0e11, "nlot": 40, "bfreq": 2, "sfreq": 1,
              "blot": 60, "slot": 20},
             {"broker_code": "CC", "bval": 2.0e11, "sval": 4.5e11,
              "nval": -2.5e11, "nlot": -25, "bfreq": 3, "sfreq": 5,
              "blot": 20, "slot": 45},
         ]},
    ],
}

BROKER_TOP = {
    "symbol": "BBCA.JK", "start": "2026-08-22", "end": "2026-09-21",
    "origin": "all", "cohort": "all", "foreign": False,
    "top_buyers": [
        {"rank": 1, "broker_code": "KZ", "net_idr": 6.4e11,
         "buy_idr": 1.16e12, "sell_idr": 5.1e11, "foreign_net_idr": 6.8e11},
        {"rank": 2, "broker_code": "YU", "net_idr": 3.0e11,
         "buy_idr": 6.0e11, "sell_idr": 3.0e11, "foreign_net_idr": 1.0e11},
    ],
    "top_sellers": [
        {"rank": 1, "broker_code": "BK", "net_idr": -3.1e11,
         "buy_idr": 5.6e11, "sell_idr": 8.8e11, "foreign_net_idr": -3.3e11},
        {"rank": 2, "broker_code": "MG", "net_idr": -1.0e11,
         "buy_idr": 2.0e11, "sell_idr": 3.0e11, "foreign_net_idr": -0.5e11},
    ],
}

SCREEN = {
    "results": [
        {"symbol": "BBCA.JK", "company_name": "PT Bank Central Asia Tbk.",
         "query_values": {"sub_sector": "Banks", "market_cap": 7.5e14}},
        {"symbol": "BBRI.JK", "company_name": "PT Bank Rakyat",
         "query_values": {"sub_sector": "Banks", "market_cap": 4.1e14}},
        {"symbol": "BMRI.JK", "company_name": "PT Bank Mandiri",
         "query_values": {"sub_sector": "Banks", "market_cap": 3.6e14}},
    ],
    "pagination": {"total_count": 48, "showing": 3},
    "llm_translation": {"natural_query": "top banks", "translated_params": {},
                        "message": None},
}


async def test_movers_diverging_with_groups(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("movers"))
    spec = await charts.judge_and_extract(
        "sectors_top_movers", _envelope(TOP_MOVERS), "top movers"
    )
    assert spec["kind"] == "diverging_bar" and spec["format"] == "percent"
    groups = {p["group"] for p in spec["data"]}
    assert groups == {"Top gainers 1d", "Top losers 1d"}
    assert spec["data"][0]["symbol"] == "JECX"  # .JK stripped


async def test_traded_bars_latest_day(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("traded_bars"))
    spec = await charts.judge_and_extract(
        "sectors_most_traded", _envelope(MOST_TRADED), "most traded today"
    )
    assert spec["kind"] == "bar"
    assert "2026-09-22" in spec["title"]
    assert [p["symbol"] for p in spec["data"]] == ["GOTO", "DEWA"]


async def test_traded_trend_multi_series(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("traded_trend"))
    spec = await charts.judge_and_extract(
        "sectors_most_traded", _envelope(MOST_TRADED), "volume trend"
    )
    assert spec["kind"] == "line"
    keys = {s["key"] for s in spec["series"]}
    assert keys <= {"GOTO", "DEWA", "BRMS"}
    assert spec["data"][0]["date"] == "2026-09-18"


async def test_broker_net_bars_aggregates(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("broker_net_bars"))
    spec = await charts.judge_and_extract(
        "sectors_broker_summary", _envelope(BROKER_SUMMARY), "siapa net buy"
    )
    assert spec["kind"] == "diverging_bar" and spec["format"] == "idr"
    nets = {p["symbol"]: p["net"] for p in spec["data"]}
    assert nets["KZ"] == 6.0e11 + 4.0e11
    assert nets["BK"] == -3.0e11


async def test_broker_rank_bars(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("broker_rank_bars"))
    spec = await charts.judge_and_extract(
        "sectors_broker_top", _envelope(BROKER_TOP), "top brokers BBCA"
    )
    assert spec["kind"] == "diverging_bar"
    groups = {p["group"] for p in spec["data"]}
    assert groups == {"Top buyers", "Top sellers"}


async def test_screen_bars_first_numeric_metric(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("screen_bars"))
    spec = await charts.judge_and_extract(
        "sectors_screen", _envelope(SCREEN), "top banks by mcap"
    )
    assert spec["kind"] == "bar"
    assert spec["series"][0]["key"] == "market_cap"
    assert spec["data"][0]["market_cap"] == 7.5e14


async def test_screen_without_query_values_returns_none(monkeypatch):
    bare = {"results": [{"symbol": "BBCA.JK", "company_name": "x"}]}
    monkeypatch.setattr(charts, "jev_ask", _view("screen_bars"))
    assert await charts.judge_and_extract(
        "sectors_screen", _envelope(bare), "x"
    ) is None


COMPANY_REPORT = {
    "symbol": "BBCA.JK", "company_name": "PT Bank Central Asia Tbk.",
    "financials": {
        "historical_financials": [
            {"year": 2023, "revenue": 9.0e13, "earnings": 4.5e13},
            {"year": 2024, "revenue": 1.0e14, "earnings": 5.0e13},
            {"year": 2025, "revenue": 1.1e14, "earnings": 5.7e13},
        ],
    },
    "peers": [
        {"peers_data": {"companies": [
            {"symbol": "BBCA.JK", "company_name": "BCA",
             "market_cap": 7.6e14, "net_income": 5.7e13},
            {"symbol": "BBRI.JK", "company_name": "BRI",
             "market_cap": 4.1e14, "net_income": 5.9e13},
            {"symbol": "BMRI.JK", "company_name": "Mandiri",
             "market_cap": 3.6e14, "net_income": 6.7e13},
        ]}, "group_name": {"sector": "Financials"}}
    ],
    "dividend": {
        "historical_dividends": {
            "2024": {"breakdown": [], "total_yield": 0.03,
                     "total_dividend": 280},
            "2025": {"breakdown": [], "total_yield": 0.04,
                     "total_dividend": 295},
            "2026": {"breakdown": [], "total_yield": 0.05,
                     "total_dividend": 301},
        },
        "yield_ttm": 0.05,
    },
    "valuation": {
        "historical_valuation": [
            {"year": 2023, "pb": 4.5, "pe": 24.0, "ps": 11.0},
            {"year": 2024, "pb": 4.6, "pe": 25.0, "ps": 11.5},
            {"year": 2025, "pb": 4.7, "pe": 25.6, "ps": 11.9},
        ],
    },
}

SUBSECTOR_REPORT = {
    "sector": "Financials", "sub_sector": "Banks",
    "market_cap": {
        "total_market_cap": 2.2e15,
        "quarterly_market_cap": {
            "prev_ttm_mcap": {"2025.Q3": 3.5e15, "2025.Q4": 3.1e15},
            "current_ttm_mcap": {"2026.Q1": 2.9e15, "2026.Q2": 2.8e15},
        },
    },
    "companies": {
        "top_companies": {
            "top_mcap": {
                "BBCA.JK": {"name": "BCA", "market_cap": 7.5e14},
                "BBRI.JK": {"name": "BRI", "market_cap": 4.1e14},
                "BMRI.JK": {"name": "Mandiri", "market_cap": 3.6e14},
            },
        },
    },
}


@pytest.mark.parametrize("view,kind", [
    ("financials_trend", "grouped_bar"),
    ("peers_bars", "bar"),
    ("dividend_history", "bar"),
    ("valuation_trend", "line"),
])
async def test_company_report_views(monkeypatch, view, kind):
    monkeypatch.setattr(charts, "jev_ask", _view(view))
    spec = await charts.judge_and_extract(
        "sectors_company_report", _envelope(COMPANY_REPORT), "laporan BBCA"
    )
    assert spec is not None and spec["kind"] == kind
    assert len(spec["data"]) == 3


async def test_subsector_views(monkeypatch):
    monkeypatch.setattr(charts, "jev_ask", _view("subsector_mcap_trend"))
    spec = await charts.judge_and_extract(
        "sectors_subsector_report", _envelope(SUBSECTOR_REPORT), "tren banks"
    )
    assert spec["kind"] == "area" and spec["format"] == "idr"
    assert [p["quarter"] for p in spec["data"]] == [
        "2025.Q3", "2025.Q4", "2026.Q1", "2026.Q2"
    ]

    monkeypatch.setattr(charts, "jev_ask", _view("subsector_top_mcap"))
    spec = await charts.judge_and_extract(
        "sectors_subsector_report", _envelope(SUBSECTOR_REPORT), "terbesar"
    )
    assert spec["kind"] == "bar"
    assert spec["data"][0]["symbol"] == "BBCA"


async def test_history_attaches_charts_to_closing_assistant(monkeypatch):
    from app.agent import service

    values = {
        "messages": [
            HumanMessage(content="harga BBCA"),
            AIMessage(content="", tool_calls=[{"name": "sectors_daily_prices",
                                               "args": {"symbol": "BBCA"},
                                               "id": "c",
                                               "type": "tool_call"}]),
            ToolMessage(content="{}", tool_call_id="c",
                        name="sectors_daily_prices"),
            AIMessage(content="BBCA ditutup 6.300 (+2%)."),
        ],
        "charts": [
            {"id": "c1", "view": "price_volume", "kind": "price_volume",
             "title": "BBCA daily close", "x": {}, "series": [], "data": [],
             "fetched_at": "f", "format": "number", "anchor": 2},
        ],
    }
    fake_graph = SimpleNamespace(
        aget_state=AsyncMock(
            return_value=SimpleNamespace(values=values)
        )
    )
    monkeypatch.setattr(service, "_graph", fake_graph)

    out = await service.get_thread_messages("tid")
    # The empty tool-call carrier folds into the closing assistant entry —
    # it carries the turn's tool steps and its charts.
    assert len(out) == 2
    assert out[0]["role"] == "user" and "charts" not in out[0]
    assert out[1]["role"] == "assistant"
    assert out[1]["tools"] == [
        {"name": "sectors_daily_prices", "args": {"symbol": "BBCA"}}
    ]
    assert out[1]["charts"][0]["id"] == "c1"
    assert "anchor" not in out[1]["charts"][0]
