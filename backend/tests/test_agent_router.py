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
async def test_jev_choice_routes_to_deep_research(monkeypatch):
    async def fake_ask(state, questions):
        return SimpleNamespace(
            choices={"route": SimpleNamespace(choice="deep_research")}
        )

    monkeypatch.setattr(router, "jev_ask", fake_ask)
    assert await router.router(_state("compare BBCA vs BMRI deeply"), {}) == {
        "workflow": "deep_research"
    }


@pytest.mark.asyncio
async def test_router_passes_recent_turns_for_followups(monkeypatch):
    """A bare follow-up like 'what if I miss it?' needs the prior turns in the
    JEV payload or it misroutes to general."""
    seen = {}

    async def fake_ask(state, questions):
        seen.update(state)
        return SimpleNamespace(
            choices={"route": SimpleNamespace(choice="corporate_actions")}
        )

    monkeypatch.setattr(router, "jev_ask", fake_ask)
    state = _state("what will happen if i miss this?")
    state["messages"] = [
        HumanMessage(content="does BAJA have corporate actions?"),
        *state["messages"][:0],
    ]
    state["messages"].append(HumanMessage(content="what will happen if i miss this?"))
    await router.router(state, {})
    assert "BAJA" in seen["recent_messages"]
    assert seen["latest_user_message"] == "what will happen if i miss this?"


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
