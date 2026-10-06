"""LangGraph nodes for the aksi pipeline.

Each node's update is merged over the graph state; `emit` streams progress to
SSE. `investigate` runs a small LLM tool loop over the cached Sectors tools —
it costs zero further credits when every tool hits the cache.
"""

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.core.config import settings
from app.core.llm import get_chat_model
from app.aksi import briefs, budget, calc, events, findings, sources, store
from app.sectors import tools as st

INVESTIGATE_ALLOW = {
    "sectors_news", "sectors_broker_top", "sectors_insider_filings",
    "sectors_shareholders", "sectors_daily_prices", "sectors_company_corporate_actions",
}
INVESTIGATE_TOOLS: dict[str, BaseTool] = {
    t.name: t for t in st.TOOLS if t.name in INVESTIGATE_ALLOW
}
INVESTIGATE_LIMIT = 6
PACK_MIN_PER_EVENT = 3

# Pack keys match what `findings.extract` reads; each maps to a raw source read.
PACK = {
    "right_issue": ("prices", "filings", "shareholders", "ownership"),
    "warrant": ("prices",),
    "dividend": ("prices",),
}
_PACK_TOOL = {
    "prices": "sectors_daily_prices",
    "filings": "sectors_insider_filings",
    "shareholders": "sectors_shareholders",
    "ownership": "sectors_company_report",
}

_PROMPT = (Path(__file__).parent.parent / "prompts" / "aksi_investigate.md").read_text(
    encoding="utf-8")

_investigator = get_chat_model(settings.MODEL_NAME, temperature=0.2, timeout=45,
                               max_retries=1, reasoning_effort="none").bind_tools(
    list(INVESTIGATE_TOOLS.values()), tool_choice="auto")


async def emit(config, event: str, data: dict) -> None:
    fn = (config.get("configurable") or {}).get("emit")
    if fn:
        out = fn(event, data)
        if asyncio.iscoroutine(out):
            await out


async def emit_tool(config, name: str, status: str, **extra) -> None:
    await emit(config, "tool", {"name": name, "status": status, **extra})


def _pack_args(key: str, symbol: str, as_of: date) -> dict:
    """Tool-style args for a pack read — also the args in the SSE tool event."""
    if key == "prices":
        return {"symbol": symbol, "start": (as_of - timedelta(days=89)).isoformat(),
                "end": as_of.isoformat()}
    if key == "filings":
        return {"symbol": symbol, "start": (as_of - timedelta(days=45)).isoformat(),
                "end": as_of.isoformat()}
    if key == "shareholders":
        return {"symbol": symbol, "year": as_of.year}
    return {"symbol": symbol, "sections": ["ownership"]}


_PACK_FETCH = {
    "prices": sources.daily_prices,
    "filings": sources.insider_filings,
    "shareholders": sources.shareholders,
    "ownership": sources.company_report,
}


def _step(node: str, ev: dict | None = None) -> dict:
    return {"node": node, **({"event_id": ev["id"]} if ev else {})}


def _clamp(args: dict, as_of: date) -> dict:
    """Anti-lookahead for replays: no tool window may end after `as_of`, and
    `refresh` is never forwarded (the aksi pipeline reads through the cache)."""
    out = dict(args)
    if out.get("end") and str(out["end"])[:10] > as_of.isoformat():
        out["end"] = as_of.isoformat()
    if isinstance(out.get("year"), int) and out["year"] > as_of.year:
        out["year"] = as_of.year
    out.pop("refresh", None)
    return out


async def scan(state: dict, config) -> dict:
    await emit(config, "step", _step("scan"))
    as_of = date.fromisoformat(state["as_of"])
    start, end = events.scan_window(as_of)

    args = {"types": events.KINDS, "start": start, "end": end}
    await emit_tool(config, "sectors_corporate_actions", "call", args=args)
    env = await sources.calendar(events.KINDS, start, end)
    await emit_tool(config, "sectors_corporate_actions",
                    "done" if env.get("status") == 200 else "error")
    spent = budget.cost("sectors_corporate_actions", {"types": events.KINDS}, env)

    calendar = env.get("data") if env.get("status") == 200 else {}
    picked = events.normalize(calendar or {}, state["holdings"], as_of)
    for ev in picked:
        await emit(config, "event_found", events.public(ev))
    return {"events": picked, "cursor": 0,
            "credits_used": state["credits_used"] + spent}


async def load_pack(state: dict, config) -> dict:
    ev = state["events"][state["cursor"]]
    await emit(config, "step", _step("load_pack", ev))
    as_of = date.fromisoformat(state["as_of"])
    pack: dict[str, dict] = {}
    spent = 0
    for key in PACK.get(ev["kind"], ()):
        name = _PACK_TOOL[key]
        await emit_tool(config, name, "call", args=_pack_args(key, ev["symbol"], as_of))
        pack[key] = await _PACK_FETCH[key](**_pack_args(key, ev["symbol"], as_of))
        spent += 1 if pack[key].get("source") == "upstream" else 0
        await emit_tool(config, name, "done" if pack[key].get("status") == 200 else "error")
    return {"work": {"event": ev, "pack": pack},
            "credits_used": state["credits_used"] + spent}


async def calculate(state: dict, config) -> dict:
    work = state["work"]
    ev = work["event"]
    await emit(config, "step", _step("calculate", ev))
    as_of = date.fromisoformat(state["as_of"])
    price_rows = findings.rows(work["pack"].get("prices"))
    figs = calc.figures_for(ev, price_rows, as_of)
    await emit(config, "numbers", {"event_id": ev["id"], "figures": figs})
    return {"work": {**work, "figures": figs}}


async def investigate(state: dict, config) -> dict:
    work = state["work"]
    ev, pack = work["event"], work["pack"]
    await emit(config, "step", _step("investigate", ev))
    as_of = date.fromisoformat(state["as_of"])
    extra: list[dict] = []
    spent = 0

    found = findings.extract(ev, pack, [], as_of)
    if not findings.needs_investigation(found):
        return {"work": {**work, "findings": found, "investigation": 0}}

    left = state["budget"] - state["credits_used"]
    remaining = len(state["events"]) - state["cursor"] - 1
    budget_hint = max(0, left - remaining * PACK_MIN_PER_EVENT)
    payload = {
        "event": events.public(ev),
        "findings": [findings.public(f) for f in found],
        "budget_credits": budget_hint,
    }
    messages = [SystemMessage(content=_PROMPT), HumanMessage(content=json.dumps(payload))]
    calls = 0
    for _ in range(INVESTIGATE_LIMIT):
        try:
            reply = await _investigator.ainvoke(messages)
        except Exception:
            break
        messages.append(reply)
        tool_calls = getattr(reply, "tool_calls", None) or []
        if not tool_calls:
            break
        for call in tool_calls:
            tool = INVESTIGATE_TOOLS.get(call["name"])
            if tool is None:
                messages.append(ToolMessage(content="not allowed", tool_call_id=call["id"]))
                continue
            if calls >= INVESTIGATE_LIMIT or spent >= left:
                messages.append(ToolMessage(content="budget exhausted",
                                            tool_call_id=call["id"]))
                continue
            args = _clamp(call.get("args") or {}, as_of)
            await emit_tool(config, call["name"], "call", args=args)
            out = await tool.ainvoke(args)
            envelope = json.loads(out) if isinstance(out, str) else out
            spent += budget.cost(call["name"], args, envelope)
            calls += 1
            extra.append({"tool": call["name"], "args": args, "envelope": envelope})
            await emit_tool(config, call["name"],
                            "done" if envelope.get("status") == 200 else "error",
                            source=envelope.get("source"))
            messages.append(ToolMessage(content=json.dumps(envelope.get("data"))[:4000],
                                        tool_call_id=call["id"]))
    if calls:
        found = findings.extract(ev, pack, extra, as_of)
    return {"work": {**work, "findings": found, "investigation": calls},
            "credits_used": state["credits_used"] + spent}


async def brief(state: dict, config) -> dict:
    work = state["work"]
    ev, figs, found = work["event"], work["figures"], work.get("findings", [])
    await emit(config, "step", _step("brief", ev))
    for f in found:
        await emit(config, "finding", {"event_id": ev["id"], **findings.public(f)})
    result = await briefs.produce(ev, figs, found)
    await emit(config, "brief", {"event_id": ev["id"], **result})
    saved = {"event": events.public(ev), "figures": figs,
             "findings": [findings.public(f) for f in found], "brief": result}
    await store.append_event(state["report_id"], saved, state["credits_used"])
    return {"work": {}, "results": [saved], "cursor": state["cursor"] + 1}


async def finish(state: dict, config) -> dict:
    await store.finish_report(state["report_id"], "done", state["credits_used"])
    await emit(config, "budget", {"credits_used": state["credits_used"],
                                  "budget": state["budget"]})
    return {}
