"""JEV Choice router.

Registered workflows live in WORKFLOWS. New workflows = one entry here plus
a prompt hint in nodes._WORKFLOW_HINTS if the agent needs guidance. When JEV
is unavailable the router fails closed to `general` — the only workflow
guaranteed to be side-effect free.
"""

import logging

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agent.messages import recent_context
from app.agent.state import ChatState
from app.core.jev import Choice, jev_ask

logger = logging.getLogger(__name__)

WORKFLOWS: dict[str, str] = {
    "general": "General conversation, greetings, explanations, and non-market questions.",
    "sectors_data": (
        "IDX market data questions answerable with a few lookups — prices, "
        "screening, company or subsector reports, rankings, broker activity, "
        "foreign flow, filings, suspensions, corporate actions, listing "
        "performance, market news."
    ),
    "deep_research": (
        "Multi-step research — 'analyze X', 'compare A vs B', deep dives and "
        "due-diligence questions that need several data pulls before an "
        "answer can be synthesized."
    ),
    "corporate_actions": (
        "Corporate actions — rights issues (HMETD), dividends, warrants — for "
        "the user's own shares: entitlement, cost, dilution, deadlines. Also "
        "managing the user's tracked stock holdings (add/update/remove "
        "tickers) and running or reading a full corporate-actions check on "
        "their portfolio."
    ),
}

_DEFAULT = "general"


def _last_user_query(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            return m.content
    return ""


async def router(state: ChatState, config: RunnableConfig) -> dict:
    result = await jev_ask(
        {
            "latest_user_message": _last_user_query(state.get("messages", [])),
            "recent_messages": recent_context(state.get("messages", [])),
            "conversation_summary": state.get("summary", ""),
        },
        {
            "route": Choice(
                instructions=(
                    "Pick the workflow that best handles the user's message. "
                    "Follow-up messages rely on recent_messages for topic — "
                    "e.g. 'what if I miss it?' after a BAJA rights issue "
                    "answer is still corporate_actions."
                ),
                criteria=dict(WORKFLOWS),
            )
        },
    )

    choice = None
    if result is not None:
        answer = result.choices.get("route")
        choice = answer.choice if answer else None
    if choice not in WORKFLOWS:
        return {"workflow": _DEFAULT}
    return {"workflow": choice}
