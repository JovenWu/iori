"""Agent node: compose the per-turn system prompt and call the chat model.

The system prompt is assembled fresh each turn from `system.md` plus the
read-only blocks the context manager fetched (summary, recalled memories,
related past chats) — they are never written into `messages`, so checkpoints
keep a clean conversational history.
"""

import logging
from pathlib import Path

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agent.state import ChatState
from app.core.config import settings
from app.core.llm import get_chat_model

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

# Extension point: Sectors tools register here; the graph's tools node and
# the agent's tool_calls routing already exist.
TOOLS: list = []

_agent_base = get_chat_model(settings.MODEL_NAME, temperature=0.3, streaming=True)
# bind_tools([]) would send an empty "tools" array some providers reject.
agent_llm = _agent_base.bind_tools(TOOLS) if TOOLS else _agent_base


def _compose_system(state: ChatState) -> str:
    parts = [_SYSTEM_PROMPT]
    if state.get("summary"):
        parts.append(f"Conversation summary so far:\n{state['summary']}")
    if state.get("recalled_memories"):
        parts.append(state["recalled_memories"])
    if state.get("related_threads"):
        parts.append(state["related_threads"])
    return "\n\n".join(parts)


async def agent(state: ChatState, config: RunnableConfig) -> dict:
    active = state["messages"][state.get("summarized_upto", 0) :]
    response = await agent_llm.ainvoke(
        [SystemMessage(content=_compose_system(state)), *active]
    )
    return {"messages": [response]}
