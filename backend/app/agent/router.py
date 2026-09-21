"""JEV Choice router.

Registered workflows live in WORKFLOWS; the groundwork ships `general` only.
Adding a Sectors workflow later = one entry here + a node/edge in the graph.
When JEV is unavailable the router fails closed to `general` — the only
workflow guaranteed to exist.
"""

import logging

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agent.state import ChatState
from app.core.jev import Choice, jev_ask

logger = logging.getLogger(__name__)

WORKFLOWS: dict[str, str] = {
    "general": "General conversation, questions, and analysis.",
}

_DEFAULT = "general"


def _last_user_query(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            return m.content
    return ""


async def router(state: ChatState, config: RunnableConfig) -> dict:
    if len(WORKFLOWS) == 1:
        return {"workflow": _DEFAULT}

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
