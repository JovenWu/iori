"""The aksi LangGraph: scan → per-event pack → calculate → investigate → brief.

Run it via `aksi_graph.ainvoke(state, {"configurable": {"emit": fn}})`.
`emit` is a callable `(event_type: str, data: dict) -> None` used by the SSE
layer to stream progress.
"""

from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from app.aksi import nodes

# 4 node steps per event + scan + finish; the plan sizes this at 100 so a
# MAX_EVENTS-sized run can never hit GraphRecursionError.
RECURSION_LIMIT = 100


def _merge(left: list, right: list) -> list:
    return left + right


class AksiState(TypedDict, total=False):
    report_id: str
    user_id: int
    mode: str
    as_of: str
    holdings: list[dict]
    events: list[dict]
    cursor: int
    work: dict
    results: Annotated[list[dict], _merge]
    credits_used: int
    budget: int
    scan_failed: bool


def _has_events(state: AksiState) -> str:
    return "load_pack" if state.get("events") else "finish"


def _next(state: AksiState) -> str:
    return "load_pack" if state.get("cursor", 0) < len(state.get("events", [])) else "finish"


builder = StateGraph(AksiState)
builder.add_node("scan", nodes.scan)
builder.add_node("load_pack", nodes.load_pack)
builder.add_node("calculate", nodes.calculate)
builder.add_node("investigate", nodes.investigate)
builder.add_node("brief", nodes.brief)
builder.add_node("finish", nodes.finish)
builder.add_edge(START, "scan")
builder.add_conditional_edges("scan", _has_events)
builder.add_edge("load_pack", "calculate")
builder.add_edge("calculate", "investigate")
builder.add_edge("investigate", "brief")
builder.add_conditional_edges("brief", _next)
builder.add_edge("finish", END)
aksi_graph = builder.compile()
