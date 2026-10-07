import json

import pytest
import pytest_asyncio

from app.agent import nodes, router
from app.aksi.tools import (
    aksi_check,
    aksi_impact,
    aksi_report,
    aksi_reports,
    holdings_list,
    holdings_remove,
    holdings_save,
)
from tests import aksi_fixtures as fx

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def _bind(bound_session_maker):
    yield


def _cfg(user) -> dict:
    return {"configurable": {"user_id": user.id}}


async def test_aksi_impact_tool_returns_figures(db, _bind, monkeypatch):
    fx.install_fakes(monkeypatch)
    out = json.loads(await aksi_impact.ainvoke(
        {"symbol": "WIFI", "shares": 1000, "as_of": fx.AS_OF}))
    assert out["events"][0]["figures"]["cost_to_exercise_all"]["value"] == 2500000


async def test_aksi_impact_rejects_bad_input():
    out = json.loads(await aksi_impact.ainvoke({"symbol": "TOOLONG", "shares": 1}))
    assert out["error"] == "invalid_input"


async def test_holdings_save_list_update_remove(db, _bind, user):
    cfg = _cfg(user)
    out = json.loads(await holdings_save.ainvoke(
        {"symbol": "bbca.jk", "shares": 5000, "avg_price": 9400}, config=cfg))
    assert out["holdings"] == [{"symbol": "BBCA", "shares": 5000, "avg_price": 9400.0}]
    # Saving the same ticker updates it — never duplicates.
    out = json.loads(await holdings_save.ainvoke(
        {"symbol": "BBCA", "shares": 6000}, config=cfg))
    assert len(out["holdings"]) == 1 and out["holdings"][0]["shares"] == 6000
    out = json.loads(await holdings_list.ainvoke({}, config=cfg))
    assert out["holdings"][0]["symbol"] == "BBCA"
    out = json.loads(await holdings_remove.ainvoke({"symbol": "BBCA"}, config=cfg))
    assert out["holdings"] == []
    out = json.loads(await holdings_remove.ainvoke({"symbol": "BBCA"}, config=cfg))
    assert out["error"] == "not_found"


async def test_holdings_save_rejects_bad_input(db, _bind, user):
    cfg = _cfg(user)
    out = json.loads(await holdings_save.ainvoke(
        {"symbol": "TOOLONG", "shares": 1}, config=cfg))
    assert out["error"] == "invalid_input"
    out = json.loads(await holdings_save.ainvoke(
        {"symbol": "BBCA", "shares": 0}, config=cfg))
    assert out["error"] == "invalid_input"


async def test_aksi_report_404_before_any_check(db, _bind, user):
    out = json.loads(await aksi_report.ainvoke({}, config=_cfg(user)))
    assert out["error"] == "no_report"


async def test_aksi_check_needs_holdings(db, _bind, user):
    out = json.loads(await aksi_check.ainvoke({}, config=_cfg(user)))
    assert out["error"] == "no_holdings"


async def test_aksi_check_runs_and_persists(db, _bind, user, monkeypatch):
    fx.install_fakes(monkeypatch)
    cfg = _cfg(user)
    await holdings_save.ainvoke({"symbol": "WIFI", "shares": 1000}, config=cfg)
    await holdings_save.ainvoke({"symbol": "BBMD", "shares": 5000}, config=cfg)
    out = json.loads(await aksi_check.ainvoke({"as_of": fx.AS_OF}, config=cfg))
    assert out["status"] == "done" and out["mode"] == "replay"
    assert {e["symbol"] for e in out["events"]} == {"WIFI", "BBMD"}
    # Persisted — listed in history and openable by id, date, or mode.
    listed = json.loads(await aksi_reports.ainvoke({}, config=cfg))
    assert listed["reports"][0]["report_id"] == out["report_id"]
    by_id = json.loads(await aksi_report.ainvoke(
        {"report_id": out["report_id"]}, config=cfg))
    assert by_id["report_id"] == out["report_id"]
    by_date = json.loads(await aksi_report.ainvoke({"as_of": fx.AS_OF}, config=cfg))
    assert by_date["report_id"] == out["report_id"]


async def test_corporate_actions_workflow_is_registered():
    assert "corporate_actions" in router.WORKFLOWS
    assert "corporate_actions" in nodes._WORKFLOW_HINTS
    names = {t.name for t in nodes.AGENT_TOOLS}
    assert {"aksi_impact", "aksi_check", "aksi_report", "aksi_reports",
            "holdings_list", "holdings_save", "holdings_remove"} <= names
