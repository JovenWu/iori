"""Graph assembly.

START → context_manager → router → agent ⇄ tools → END

The tools node wraps ToolNode: after executing sectors_* calls it judges
each result for chartability (JEV) and appends chart specs to `charts`.
Compile happens in the service layer so it can attach the Postgres
checkpointer and run registry.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition

from app.agent.context import context_manager
from app.agent.nodes import agent
from app.agent.router import router
from app.agent.state import ChatState
from app.agent.tools_node import tools


def build_graph() -> StateGraph:
    graph = StateGraph(ChatState)
    graph.add_node("context_manager", context_manager)
    graph.add_node("router", router)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_edge(START, "context_manager")
    graph.add_edge("context_manager", "router")
    graph.add_edge("router", "agent")
    graph.add_conditional_edges(
        "agent", tools_condition, {"tools": "tools", END: END}
    )
    graph.add_edge("tools", "agent")
    return graph
