"""Tools node: run the sectors tools, then judge each result for a chart.

Wraps the prebuilt ToolNode — for every ToolMessage it produced, JEV decides
whether a chart adds clarity and which registered view fits; deterministic
extractors build the spec. Specs accumulate in `charts` (add reducer) with
`anchor` = the ToolMessage's index in the full history, so the API layer can
attach each chart to the assistant message that closes the turn.
"""

import logging
from typing import Sequence

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode

from app.agent.compute import compute
from app.agent.state import ChatState
from app.aksi.tools import aksi_impact
from app.sectors.charts import judge_and_extract
from app.sectors.tools import TOOLS

logger = logging.getLogger(__name__)

# Everything the agent can call — sectors tools plus local helpers. `nodes`
# decides which subset a workflow sees; the executor must accept all of them.
AGENT_TOOLS = [*TOOLS, compute, aksi_impact]

_tool_node = ToolNode(AGENT_TOOLS)


def _last_user_query(messages: Sequence[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            return m.content
    return ""


async def tools(state: ChatState, config: RunnableConfig) -> dict:
    result = await _tool_node.ainvoke(state, config)
    new_msgs = result.get("messages", [])
    base = len(state.get("messages", []))
    question = _last_user_query(state.get("messages", []))

    specs = []
    for i, m in enumerate(new_msgs):
        if not isinstance(m, ToolMessage):
            continue
        spec = await judge_and_extract(m.name or "", m.content, question)
        if spec is not None:
            spec["anchor"] = base + i
            specs.append(spec)
    if specs:
        result["charts"] = specs
    return result
