import json

import pytest
import pytest_asyncio

from app.agent import nodes, router
from app.aksi.tools import aksi_impact
from tests import aksi_fixtures as fx


@pytest_asyncio.fixture
async def _bind(bound_session_maker):
    yield


@pytest.mark.asyncio
async def test_aksi_impact_tool_returns_figures(db, _bind, monkeypatch):
    fx.install_fakes(monkeypatch)
    out = json.loads(await aksi_impact.ainvoke(
        {"symbol": "WIFI", "shares": 1000, "as_of": fx.AS_OF}))
    assert out["events"][0]["figures"]["cost_to_exercise_all"]["value"] == 2500000


@pytest.mark.asyncio
async def test_aksi_impact_rejects_bad_input():
    out = json.loads(await aksi_impact.ainvoke({"symbol": "TOOLONG", "shares": 1}))
    assert out["error"] == "invalid_input"


def test_corporate_actions_workflow_is_registered():
    assert "corporate_actions" in router.WORKFLOWS
    assert "corporate_actions" in nodes._WORKFLOW_HINTS
    assert "aksi_impact" in {t.name for t in nodes.AGENT_TOOLS}
