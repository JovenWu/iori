"""JEV Choice router: sectors_data routing and general fallback."""

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
async def test_jev_choice_routes_to_sectors(monkeypatch):
    async def fake_ask(state, questions):
        assert "route" in questions
        return SimpleNamespace(
            choices={"route": SimpleNamespace(choice="sectors_data")}
        )

    monkeypatch.setattr(router, "jev_ask", fake_ask)
    assert await router.router(_state("harga BBCA hari ini"), {}) == {
        "workflow": "sectors_data"
    }


@pytest.mark.asyncio
async def test_invalid_or_missing_choice_falls_back(monkeypatch):
    async def bad_choice(state, questions):
        return SimpleNamespace(
            choices={"route": SimpleNamespace(choice="bogus")}
        )

    monkeypatch.setattr(router, "jev_ask", bad_choice)
    assert await router.router(_state(), {}) == {"workflow": "general"}

    async def no_jev(state, questions):
        return None

    monkeypatch.setattr(router, "jev_ask", no_jev)
    assert await router.router(_state(), {}) == {"workflow": "general"}
