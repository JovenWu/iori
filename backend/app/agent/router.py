"""JEV Choice router.

Registered workflows live in WORKFLOWS. New workflows = one entry here plus
a prompt hint in nodes._WORKFLOW_HINTS if the agent needs guidance. When JEV
is unavailable the router fails closed to `general` — the only workflow
guaranteed to be side-effect free.
"""

import logging

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agent.state import ChatState
from app.core.jev import Choice, jev_ask

logger = logging.getLogger(__name__)

WORKFLOWS: dict[str, str] = {
    "general": "General conversation, greetings, explanations, and non-market questions.",
    "sectors_data": (
        "IDX market data questions — prices, screening, company or subsector "
        "reports, rankings, broker activity, foreign flow, filings, "
        "suspensions, corporate actions, listing performance, market news."
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
            "conversation_summary": state.get("summary", ""),
        },
        {
            "route": Choice(
                instructions=(
                    "Pick the workflow that best handles the user's message."
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
