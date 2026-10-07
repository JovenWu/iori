"""Recurring-job worker — fires a normal agent turn on each due job's thread.

A job run is just a `service.run_turn` keyed on the job's thread id, so live
reattach, the replay buffer, checkpointing and the finished-run notifier all
work unchanged. `last_run_at` is stamped BEFORE firing — a failed or skipped
slot never retries until the next one.
"""

import asyncio
import logging
import time
from datetime import datetime

from app.agent import service
from app.agent.runs import RunLimitError, registry
from app.core.config import settings
from app.models.scheduled_job import ScheduledJob
from app.schedules import store
from app.schedules.due import WIB

logger = logging.getLogger(__name__)


async def fire_job(job: ScheduledJob) -> str:
    """Start a run_turn for one job. Returns "fired" | "skipped" | "busy".
    Stamps last_run_at first so the slot is consumed either way."""
    tid = str(job.thread_id)
    await store.stamp_last_run(job.id, datetime.now(WIB))
    async with registry.thread_lock(tid):
        live = registry.get(tid)
        if live is not None and not live.done:
            return "skipped"  # user mid-conversation — don't interleave
        try:
            run = registry.start_run(job.user_id, tid)
        except RunLimitError:
            return "busy"
        run.task = asyncio.create_task(
            service.run_turn(run, job.user_id, tid, job.prompt,
                             lang=None, scheduled=True)
        )
        # Buffered — a user reattaching to the thread replays it like chat.
        run.emit("started",
                 {"thread_id": tid, "started_at": int(time.time() * 1000)})
    return "fired"


async def tick(now: datetime | None = None) -> int:
    """Fire every due job once. Errors are logged, not fatal — one bad job
    can't stall the tick."""
    fired = 0
    for job in await store.due_jobs(now):
        if fired >= settings.SCHEDULER_MAX_PER_TICK:
            break  # backpressure — leftovers catch the next tick
        try:
            if await fire_job(job) == "fired":
                fired += 1
        except Exception:
            logger.exception("scheduler: fire failed for job %s", job.id)
    return fired


async def scheduler_loop() -> None:
    """Lifespan task — first tick runs at startup (catch-up for slots missed
    while down), then every SCHEDULER_TICK_SECONDS."""
    while True:
        try:
            await tick()
        except Exception:
            logger.exception("scheduler tick failed")
        await asyncio.sleep(settings.SCHEDULER_TICK_SECONDS)
