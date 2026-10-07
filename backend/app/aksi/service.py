"""Aksi check producer — a detached run, like a chat turn.

Keyed `aksi:{user_id}` on the shared run registry: one active check per user,
the same caps, replay buffer and linger eviction as chat.
"""

import asyncio
import logging
import time
from datetime import date

from app.agent.runs import AgentRun, registry
from app.aksi import events, store
from app.aksi.graph import RECURSION_LIMIT, aksi_graph

logger = logging.getLogger(__name__)


def run_key(user_id: int) -> str:
    return f"aksi:{user_id}"


async def run_check(run: AgentRun, user_id: int, as_of: date | None,
                    symbols: list[str] | None, budget_cap: int) -> None:
    """Stream one check into `run`'s buffer. Never raises."""
    report_id: str | None = None
    last: dict = {}
    try:
        holdings = await store.list_holdings(user_id)
        if symbols:
            wanted = set(symbols)
            holdings = [h for h in holdings if h["symbol"] in wanted]
        today = events.today_wib()
        day = as_of or today
        mode = "replay" if day < today else "live"
        report_id = await store.create_report(user_id, mode, day, holdings)
        run.emit("started", {"report_id": report_id, "mode": mode, "as_of": day.isoformat(),
                             "started_at": int(time.time() * 1000)})
        if holdings:
            state = {"report_id": report_id, "user_id": user_id, "mode": mode,
                     "as_of": day.isoformat(), "holdings": holdings, "events": [],
                     "cursor": 0, "work": {}, "results": [], "credits_used": 0,
                     "budget": budget_cap}
            config = {"configurable": {"emit": run.emit},
                      "recursion_limit": RECURSION_LIMIT}
            async for values in aksi_graph.astream(state, config, stream_mode="values"):
                last = values
        credits = last.get("credits_used", 0)
        if last.get("scan_failed"):
            # The calendar read failed — "no events" would be a false answer.
            await store.finish_report(report_id, "error", credits)
            run.emit("error", "Market calendar unavailable.")
        else:
            await store.finish_report(report_id, "done", credits)
            run.emit("done", {"report_id": report_id,
                              "events": len(last.get("results", [])),
                              "credits_spent": credits})
    except asyncio.CancelledError:
        if report_id:
            await store.finish_report(report_id, "stopped", last.get("credits_used"))
        run.emit("stopped", {"report_id": report_id})
    except Exception:
        logger.exception("aksi check failed for user %s", user_id)
        if report_id:
            await store.finish_report(report_id, "error", last.get("credits_used"))
        run.emit("error", "Check failed.")
    finally:
        registry.finish(run)
