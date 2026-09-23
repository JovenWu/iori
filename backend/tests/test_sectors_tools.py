import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.sectors import client
from app.sectors import tools as st

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _bind_cache_db(bound_session_maker):
    yield


def _fake_get(status=200, data=None, calls=None):
    async def fake(path, params=None):
        if calls is not None:
            calls.append((path, params))
        return status, data if data is not None else {"ok": True}

    return fake


def _parse(out: str) -> dict:
    return json.loads(out)


async def test_daily_prices_normalizes_symbol_and_defaults_dates(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    out = _parse(await st.sectors_daily_prices.ainvoke({"symbol": "bbca.jk"}))
    assert out["status"] == 200 and out["source"] == "upstream"
    path, params = calls[0]
    assert path == "/v2/daily/BBCA/"
    assert params["start"] <= params["end"]  # defaults filled → stable cache key


async def test_invalid_symbol_never_calls_upstream(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    out = _parse(await st.sectors_daily_prices.ainvoke({"symbol": "TOOLONG"}))
    assert out["error"] == "invalid_symbol"
    assert calls == []


async def test_company_report_credit_minimal_default(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_company_report.ainvoke({"symbol": "BBCA"})
    _, params = calls[0]
    assert params == {"sections": "overview"}  # 1 credit, not the 8-credit default
    out = _parse(await st.sectors_company_report.ainvoke({"symbol": "BBCA"}))
    assert out["source"] == "hit" and len(calls) == 1


async def test_top_movers_explicit_credits(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_top_movers.ainvoke({})
    _, params = calls[0]
    assert params["periods"] == "1d"  # not the 10-credit upstream default
    assert params["classifications"] == "top_gainers,top_losers"


async def test_refresh_bypasses_cache(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_list_subsectors.ainvoke({})
    await st.sectors_list_subsectors.ainvoke({})
    assert len(calls) == 1
    await st.sectors_list_subsectors.ainvoke({"refresh": True})
    assert len(calls) == 2


async def test_unavailable_returns_error_json(db, monkeypatch):
    async def down(path, params=None):
        raise client.SectorsUnavailable("no key")

    monkeypatch.setattr(client, "get", down)
    out = _parse(await st.sectors_list_subsectors.ainvoke({}))
    assert out["error"] == "sectors_api_unavailable"


async def test_truncation_marks_envelope(db, monkeypatch):
    # Pin the budget — the deployed SECTORS_TOOL_MAX_CHARS can exceed the
    # fixture payloads below.
    monkeypatch.setattr(st.settings, "SECTORS_TOOL_MAX_CHARS", 8000)
    big = [{"v": "x" * 200} for _ in range(200)]
    monkeypatch.setattr(client, "get", _fake_get(data=big))
    out = _parse(await st.sectors_list_subsectors.ainvoke({}))
    assert out["truncated"] is True
    # Row-lists shrink row-wise and stay valid JSON (charts still work).
    assert isinstance(out["data"], list) and len(out["data"]) < 200

    # Non-row payloads still fall back to a truncated string.
    monkeypatch.setattr(client, "get", _fake_get(data={"blob": "x" * 20000}))
    out = _parse(await st.sectors_list_subsectors.ainvoke({"refresh": True}))
    assert out["truncated"] is True
    assert isinstance(out["data"], str) and out["data"].endswith("…")


async def test_news_forces_idx_extension(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_news.ainvoke({"symbols": "bbca, tlkm"})
    _, params = calls[0]
    assert params["extension"] == "idx"
    assert params["symbols"] == "BBCA,TLKM"


async def test_envelope_has_freshness_metadata(db, monkeypatch):
    monkeypatch.setattr(client, "get", _fake_get())
    out = _parse(await st.sectors_idx_market_summary.ainvoke({}))
    for key in ("fetched_at", "now_wib", "stale", "source", "status", "data"):
        assert key in out


async def test_default_end_anchors_to_eod_boundary(db, monkeypatch):
    """Unset `end` snaps to the last EOD publication boundary, not the wall
    clock — same upstream rows, but the cache key stays stable all data-day
    and the entry promotes to HISTORICAL instead of rolling daily."""
    from app.sectors.freshness import last_refresh_boundary

    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_daily_prices.ainvoke({"symbol": "BBCA"})
    _, params = calls[0]
    boundary = last_refresh_boundary(datetime.now(timezone.utc)).date()
    assert params["end"] == str(boundary)
    assert params["end"] <= str(datetime.now(timezone.utc).date())


async def test_window_clamps_future_end_and_rejects_reversed(db, monkeypatch):
    """Upstream 400s on end>today (UTC) or start>end — resolve locally."""
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))

    utc_today = datetime.now(timezone.utc).date()
    out = _parse(await st.sectors_foreign_flow.ainvoke({
        "symbol": "BBCA", "start": "2026-08-24",
        "end": str(utc_today + timedelta(days=1)),
    }))
    assert out["status"] == 200
    _, params = calls[0]
    assert params["end"] == str(utc_today)  # clamped, not sent as-is

    calls.clear()
    out = _parse(await st.sectors_foreign_flow.ainvoke(
        {"symbol": "BBCA", "start": "2026-09-20", "end": "2026-09-18"}))
    assert "error" in out and calls == []  # rejected before upstream


# --- deep-research endpoint tools --------------------------------------------


async def test_company_segments_path_and_year(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_company_segments.ainvoke(
        {"symbol": "asii", "financial_year": 2024}
    )
    assert calls[0] == ("/v2/company/get-segments/ASII/", {"financial_year": 2024})
    calls.clear()
    await st.sectors_company_segments.ainvoke({"symbol": "ASII", "refresh": True})
    assert calls[0] == ("/v2/company/get-segments/ASII/", {})


async def test_index_daily_validates_code(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    out = _parse(await st.sectors_index_daily.ainvoke({"index_code": "LQ45"}))
    assert out["status"] == 200
    path, params = calls[0]
    assert path == "/v2/index-daily/lq45/"
    assert params["start"] <= params["end"]  # 90-day window defaults filled
    calls.clear()
    out = _parse(await st.sectors_index_daily.ainvoke({"index_code": "nope"}))
    assert out["error"] == "invalid_index" and calls == []


async def test_index_universe_and_market_close(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_index_universe.ainvoke({"date": "2026-09-18"})
    assert calls[0] == ("/v2/index-daily/", {"date": "2026-09-18"})
    calls.clear()
    await st.sectors_market_close.ainvoke({"date": "2026-09-18", "limit": 30})
    assert calls[0] == (
        "/v2/close/", {"date": "2026-09-18", "limit": 30, "offset": 0}
    )
    calls.clear()
    future = str(datetime.now(timezone.utc).date() + timedelta(days=1))
    out = _parse(await st.sectors_market_close.ainvoke({"date": future}))
    assert "error" in out and calls == []


async def test_shareholders_year_bounds(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    out = _parse(await st.sectors_shareholders.ainvoke(
        {"symbol": "BBCA", "year": 2019}))
    assert "error" in out and calls == []  # upstream data starts 2021
    await st.sectors_shareholders.ainvoke({"symbol": "BBCA", "year": 2024})
    assert calls[0] == (
        "/v2/company/shareholders-composition/BBCA/", {"year": 2024}
    )


async def test_company_corporate_actions_path(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_company_corporate_actions.ainvoke({"symbol": "bbca"})
    assert calls[0] == ("/v2/company/corporate-actions/BBCA/", {})


async def test_broker_registry_filters(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_broker_registry.ainvoke(
        {"cohort": "retail", "origin": "foreign"}
    )
    assert calls[0] == ("/v2/brokers/", {"cohort": "retail", "origin": "foreign"})
    calls.clear()
    out = _parse(await st.sectors_broker_registry.ainvoke({"cohort": "whales"}))
    assert "error" in out and calls == []


async def test_broker_activity_window_and_filters(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_broker_activity.ainvoke(
        {"broker_code": "mg", "symbol": "bbca"}
    )
    path, params = calls[0]
    assert path == "/v2/broker-activity/MG/"
    assert params["symbol"] == "BBCA"
    assert params["start"] <= params["end"]  # 14-day window defaults filled
    calls.clear()
    out = _parse(await st.sectors_broker_activity.ainvoke(
        {"broker_code": "TOOLONG"}))
    assert out["error"] == "invalid_broker_code" and calls == []


async def test_broker_activity_top(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_broker_activity_top.ainvoke(
        {"broker_code": "MG", "foreign": True}
    )
    path, params = calls[0]
    assert path == "/v2/broker-activity/MG/top/"
    assert params["foreign"] is True


async def test_top_brokers_params(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_top_brokers.ainvoke(
        {"metric": "net", "cohort": "retail", "date": "2026-09-18"}
    )
    _, params = calls[0]
    assert params["metric"] == "net" and params["cohort"] == "retail"
    calls.clear()
    out = _parse(await st.sectors_top_brokers.ainvoke({"metric": "bananas"}))
    assert "error" in out and calls == []


async def test_foreign_flow_universe(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_foreign_flow_universe.ainvoke(
        {"order_by": "net_foreign_inflow", "limit": 10}
    )
    path, params = calls[0]
    assert path == "/v2/foreign-flow/" and params["order_by"] == "net_foreign_inflow"
    calls.clear()
    out = _parse(await st.sectors_foreign_flow_universe.ainvoke(
        {"order_by": "drop table"}))
    assert "error" in out and calls == []


async def test_free_float_single_filter(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    out = _parse(await st.sectors_free_float.ainvoke(
        {"sector": "energy", "sub_sector": "coal"}))
    assert "error" in out and calls == []  # upstream params are mutually exclusive
    await st.sectors_free_float.ainvoke({"sub_sector": "banks"})
    assert calls[0] == ("/v2/free-float/", {"sub_sector": "banks"})


async def test_quarterly_dates_and_reference_lists(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_quarterly_dates.ainvoke({"symbol": "bbca"})
    await st.sectors_list_industries.ainvoke({})
    await st.sectors_list_subindustries.ainvoke({})
    await st.sectors_list_tags.ainvoke({})
    await st.sectors_companies_with_segments.ainvoke({})
    assert [p for p, _ in calls] == [
        "/v2/company/get_quarterly_financial_dates/BBCA/",
        "/v2/industries/",
        "/v2/subindustries/",
        "/v2/tags/",
        "/v2/companies/list_companies_with_segments/",
    ]


# --- sectors_compare ----------------------------------------------------------


async def test_compare_fans_out_and_normalizes(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    out = _parse(await st.sectors_compare.ainvoke(
        {"symbols": "bbca, bmri.jk, NOTVALID", "sections": ["overview"]}))
    paths = sorted(p for p, _ in calls)
    assert paths == ["/v2/company/report/BBCA/", "/v2/company/report/BMRI/"]
    assert out["data"]["BBCA"]["status"] == 200
    assert out["data"]["BMRI"]["status"] == 200
    assert "NOTVALID" not in out["data"]


async def test_compare_dedupes_and_caps(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    syms = "bbca,BBCA," + ",".join(
        a + b + "CD" for a in "AB" for b in "EFGHIJ"
    )  # 1 dedup + 12 distinct = 13 unique
    out = _parse(await st.sectors_compare.ainvoke({"symbols": syms}))
    assert len(calls) == 8  # capped
    assert len(out["data"]) == 8


async def test_compare_filters_sections_and_rejects_all_invalid(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    await st.sectors_compare.ainvoke(
        {"symbols": "BBCA", "sections": ["valuation", "bogus", "overview"]}
    )
    _, params = calls[0]
    assert params["sections"] == "overview,valuation"
    calls.clear()
    out = _parse(await st.sectors_compare.ainvoke({"symbols": "NOPE1,XYZ"}))
    assert "error" in out and calls == []


# --- multi-symbol fan-out (comparison charts) ---------------------------------


async def test_foreign_flow_multi_symbol_fans_out(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    out = _parse(await st.sectors_foreign_flow.ainvoke(
        {"symbol": "bbca, bbri.jk"}))
    paths = sorted(p for p, _ in calls)
    assert paths == ["/v2/foreign-flow/BBCA/", "/v2/foreign-flow/BBRI/"]
    assert set(out["data"]) == {"BBCA", "BBRI"}
    assert out["data"]["BBCA"]["status"] == 200


async def test_daily_prices_multi_symbol_fans_out(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    out = _parse(await st.sectors_daily_prices.ainvoke({"symbol": "bbca,bbri"}))
    assert sorted(p for p, _ in calls) == ["/v2/daily/BBCA/", "/v2/daily/BBRI/"]
    assert set(out["data"]) == {"BBCA", "BBRI"}


async def test_multi_symbol_single_after_normalization(db, monkeypatch):
    """Dupes/non-tickers collapse to a plain single-symbol passthrough."""
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    out = _parse(await st.sectors_daily_prices.ainvoke({"symbol": "bbca,BBCA,zz"}))
    assert len(calls) == 1 and calls[0][0] == "/v2/daily/BBCA/"
    assert out["data"] == {"ok": True}  # upstream body, not a symbol map


async def test_multi_symbol_all_invalid(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    out = _parse(await st.sectors_daily_prices.ainvoke({"symbol": "XYZ,TOOLONG"}))
    assert "error" in out and calls == []


async def test_render_trims_rows_instead_of_truncating(monkeypatch):
    """Oversized envelopes keep valid structured data — nulls stripped, then
    oldest rows dropped — so charts still extract from what survived."""
    big_rows = [
        {"date": f"2026-08-{d:02d}", "revenue": i * 1e9, "dead": None,
         "pad": "x" * 400}
        for i, d in enumerate(range(1, 29))
    ]
    data = {"BBCA": {"status": 200, "data": big_rows},
            "BMRI": {"status": 200, "data": big_rows}}
    res = st.cache.CacheResult(200, data, "upstream", "f", False)
    monkeypatch.setattr(st.settings, "SECTORS_TOOL_MAX_CHARS", 4000)
    out = json.loads(st._render(res))
    assert out["truncated"] is True
    assert isinstance(out["data"], dict)  # still a symbol map, not a string
    kept = out["data"]["BBCA"]["data"]
    assert isinstance(kept, list) and len(kept) < len(big_rows)
    assert kept[-1]["date"] == big_rows[-1]["date"]  # newest rows kept
    assert "dead" not in kept[-1]  # nulls stripped
    assert len(json.dumps(out)) <= 4500


async def test_quarterly_financials_multi_symbol_fans_out(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "get", _fake_get(calls=calls))
    out = _parse(await st.sectors_quarterly_financials.ainvoke(
        {"symbol": "bbca,bbri", "n_quarters": 3}))
    paths = sorted(p for p, _ in calls)
    assert paths == ["/v2/financials/quarterly/BBCA/",
                     "/v2/financials/quarterly/BBRI/"]
    assert set(out["data"]) == {"BBCA", "BBRI"}
    assert all(params["n_quarters"] == 3 for _, params in calls)
