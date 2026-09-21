"""Graph assembly.

START → context_manager → router → agent ⇄ tools → END

The tools node is intentionally empty for the groundwork — `tools_condition`
always routes agent → END until Sectors tools register in `nodes.TOOLS`.
Compile happens in the service layer so it can attach the Postgres
checkpointer and run registry.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.agent.context import context_manager
from app.agent.nodes import TOOLS, agent
from app.agent.router import router
from app.agent.state import ChatState


def build_graph() -> StateGraph:
    graph = StateGraph(ChatState)
    graph.add_node("context_manager", context_manager)
    graph.add_node("router", router)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "context_manager")
    graph.add_edge("context_manager", "router")
    graph.add_edge("router", "agent")
    graph.add_conditional_edges(
        "agent", tools_condition, {"tools": "tools", END: END}
    )
    graph.add_edge("tools", "agent")
    return graph
