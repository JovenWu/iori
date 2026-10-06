"""The aksi graph end to end: real tools + cache, mocked upstream/LLM/JEV."""

import json
from datetime import date

import pytest
import pytest_asyncio

from app.aksi import sources, store
from app.aksi.graph import RECURSION_LIMIT, aksi_graph
from app.sectors import tools as st
from tests import aksi_fixtures as fx

pytestmark = pytest.mark.asyncio

HOLDINGS = [{"symbol": "WIFI", "shares": 1000, "avg_price": None},
            {"symbol": "BBMD", "shares": 5000, "avg_price": None}]


@pytest_asyncio.fixture(autouse=True)
async def _bind(bound_session_maker):
    yield


def _state(report_id: str, user_id: int, holdings: list[dict]) -> dict:
    return {"report_id": report_id, "user_id": user_id, "mode": "replay", "as_of": fx.AS_OF,
            "holdings": holdings, "events": [], "cursor": 0, "work": {}, "results": [],
            "credits_used": 0, "budget": 25}


async def _run(user, holdings):
    emitted: list[tuple[str, object]] = []
    report_id = await store.create_report(user.id, "replay", date(2025, 7, 10), holdings)
    final = await aksi_graph.ainvoke(
        _state(report_id, user.id, holdings),
        {"configurable": {"emit": lambda t, d: emitted.append((t, d))},
         "recursion_limit": RECURSION_LIMIT},
    )
    return final, emitted, report_id


async def test_graph_processes_every_event(db, user, monkeypatch):
    fx.install_fakes(monkeypatch)
    final, emitted, report_id = await _run(user, HOLDINGS)

    assert [r["event"]["event_id"] for r in final["results"]] == [
        "BBMD:dividend:2025-07-14", "WIFI:right_issue:2025-07-02"]
    assert final["credits_used"] == 9  # calendar 4 + BBMD prices 1 + WIFI pack 4
    types = [t for t, _ in emitted]
    assert types.count("event_found") == 2 and types.count("numbers") == 2
    assert types.count("brief") == 2 and "budget" in types

    dividend, rights = final["results"]
    assert dividend["figures"]["gross_dividend"]["value"] == 171250
    assert dividend["brief"]["gate"]["template"] is True  # rights-issue draft doesn't fit
    assert rights["figures"]["rights_entitled"]["value"] == 1250
    assert rights["figures"]["terp"]["inputs"]["p_cum"] == 3000
    assert [f["id"] for f in rights["findings"]] == [
        "controller_change", "price_vs_exercise", "ownership_shift"]
    assert rights["brief"]["gate"]["template"] is False
    assert "Rp2.500.000" in rights["brief"]["summary_id"]

    report = await store.get_report(user.id, report_id)
    assert len(report["events"]) == 2 and report["credits_spent"] == 9


async def test_graph_without_matching_events_stops_after_scan(db, user, monkeypatch):
    fx.install_fakes(monkeypatch)
    final, emitted, _ = await _run(user, [{"symbol": "TLKM", "shares": 100, "avg_price": None}])
    assert final["results"] == [] and final["credits_used"] == 4
    assert [d["name"] for t, d in emitted if t == "tool" and d.get("status") == "call"] == [
        "sectors_corporate_actions"]


async def test_sources_share_cache_entries_with_tools(db, monkeypatch):
    calls: list[str] = []
    fx.install_fakes(monkeypatch, calls)
    raw = await sources.daily_prices("WIFI", "2025-04-12", "2025-07-10")
    out = json.loads(await st.sectors_daily_prices.ainvoke(
        {"symbol": "WIFI", "start": "2025-04-12", "end": "2025-07-10"}))
    assert raw["source"] == "upstream" and out["source"] == "hit"
    assert calls == ["/v2/daily/WIFI/"]
