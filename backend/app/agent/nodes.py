"""Agent node: compose the per-turn system prompt and call the chat model.

The system prompt is assembled fresh each turn from `system.md` plus the
read-only blocks the context manager fetched (summary, recalled memories,
related past chats) — they are never written into `messages`, so checkpoints
keep a clean conversational history.
"""

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agent.state import ChatState
from app.agent.tools_node import AGENT_TOOLS
from app.core.config import settings
from app.core.llm import get_chat_model

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_WIB = ZoneInfo("Asia/Jakarta")

# Router-chosen workflow → prompt addendum. Keys must exist in
# router.WORKFLOWS.
_WORKFLOW_HINTS = {
    "sectors_data": (
        "The user needs IDX market data — use the sectors_* tools rather than "
        "memory for market facts. Keep calls cheap: prefer the structured "
        "screener `where` over `q`, request only needed report "
        "sections/periods, and don't paginate unless asked. Cite the data's "
        "fetched_at when quoting figures; if a result is marked stale and the "
        "question depends on the latest data, retry the tool with refresh=true."
    ),
    "deep_research": (
        "Multi-step research task — gather broadly before answering: pull each "
        "company's report sections, quarterly financials, segments, and "
        "flow/ownership data; use sectors_compare for multi-ticker pulls, "
        "sectors_index_daily for benchmark-relative performance, and compute "
        "for every derived figure — never do arithmetic mentally. Then "
        "synthesize: headline answer, evidence, risks, and what the data "
        "doesn't cover. Cite fetched_at for the figures quoted."
    ),
}

_agent_base = get_chat_model(settings.MODEL_NAME, temperature=0.3, streaming=True)
agent_llm = _agent_base.bind_tools(AGENT_TOOLS)

# Router-chosen workflow → runnable. `general` is deliberately tool-less so
# small talk can never spend API credits; any other workflow — including a
# misroute — gets the full set rather than failing a data question.
_LLM_BY_WORKFLOW = {"general": _agent_base}


def _compose_system(state: ChatState) -> str:
    now = datetime.now(_WIB).isoformat(timespec="seconds")
    parts = [_SYSTEM_PROMPT, f"Current time: {now} (Asia/Jakarta, WIB)."]
    if hint := _WORKFLOW_HINTS.get(state.get("workflow", "")):
        parts.append(hint)
    if state.get("summary"):
        parts.append(f"Conversation summary so far:\n{state['summary']}")
    if state.get("recalled_memories"):
        parts.append(state["recalled_memories"])
    if state.get("related_threads"):
        parts.append(state["related_threads"])
    return "\n\n".join(parts)


async def agent(state: ChatState, config: RunnableConfig) -> dict:
    active = state["messages"][state.get("summarized_upto", 0) :]
    llm = _LLM_BY_WORKFLOW.get(state.get("workflow") or "", agent_llm)
    response = await llm.ainvoke(
        [SystemMessage(content=_compose_system(state)), *active], config
    )
    return {"messages": [response]}
