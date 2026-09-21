import json

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
    big = [{"v": "x" * 200} for _ in range(200)]
    monkeypatch.setattr(client, "get", _fake_get(data=big))
    out = _parse(await st.sectors_list_subsectors.ainvoke({}))
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
