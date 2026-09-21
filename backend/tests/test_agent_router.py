"""JEV Choice router: single-workflow short-circuit, choice, fallback."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from app.agent import router


def _state(msg="hi"):
    return {
        "messages": [HumanMessage(content=msg)],
        "summary": "",
        "summarized_upto": 0,
    }


@pytest.mark.asyncio
async def test_single_workflow_short_circuits(monkeypatch):
    async def explode(state, questions):
        raise AssertionError("jev_ask must not be called with one workflow")

    monkeypatch.setattr(router, "jev_ask", explode)
    assert await router.router(_state(), {}) == {"workflow": "general"}


@pytest.mark.asyncio
async def test_jev_choice_routes(monkeypatch):
    monkeypatch.setitem(router.WORKFLOWS, "sectors", "Sectors data workflow.")

    async def fake_ask(state, questions):
        return SimpleNamespace(
            choices={"route": SimpleNamespace(choice="sectors", confidence=0.9)}
        )

    monkeypatch.setattr(router, "jev_ask", fake_ask)
    assert await router.router(_state(), {}) == {"workflow": "sectors"}


@pytest.mark.asyncio
async def test_invalid_or_missing_choice_falls_back(monkeypatch):
    monkeypatch.setitem(router.WORKFLOWS, "sectors", "Sectors data workflow.")

    async def bad_choice(state, questions):
        return SimpleNamespace(
            choices={"route": SimpleNamespace(choice="bogus", confidence=0.9)}
        )

    monkeypatch.setattr(router, "jev_ask", bad_choice)
    assert await router.router(_state(), {}) == {"workflow": "general"}

    async def no_jev(state, questions):
        return None

    monkeypatch.setattr(router, "jev_ask", no_jev)
    assert await router.router(_state(), {}) == {"workflow": "general"}
