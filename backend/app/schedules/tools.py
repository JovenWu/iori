"""Schedule tools — the agent manages its own recurring jobs.

ChatGPT-tasks feel: "every weekday at 5pm, scan my holdings" creates a job
that fires a normal turn on its own thread. All times are WIB.
"""

import json
from datetime import time

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.schedules import store

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _uid(config: RunnableConfig) -> int | None:
    uid = (config.get("configurable") or {}).get("user_id")
    try:
        return int(uid) if uid is not None else None
    except (TypeError, ValueError):
        return None


def _cadence(job: dict) -> str:
    t = job["run_time"]
    if job["frequency"] == "daily":
        return f"daily {t} WIB"
    if job["frequency"] == "weekly":
        return f"every {_WEEKDAYS[job['weekday']]} {t} WIB"
    return f"monthly day {job['day_of_month']} {t} WIB"


def _out(job: dict) -> dict:
    return {"job": job, "cadence": _cadence(job)}


def _parse_time(raw: str | None) -> time | None:
    if raw is None:
        return None
    return time.fromisoformat(raw)


@tool
async def schedule_list(config: RunnableConfig) -> str:
    """List the user's scheduled jobs — name, prompt, cadence, next run time
    and whether each is enabled."""
    uid = _uid(config)
    if uid is None:
        return json.dumps({"error": "no_user"})
    jobs = [store.job_dict(j) for j in await store.list_jobs(uid)]
    for j in jobs:
        j["cadence"] = _cadence(j)
    return json.dumps({"jobs": jobs}, default=str)


@tool
async def schedule_create(name: str, prompt: str, frequency: str,
                          config: RunnableConfig,
                          run_time: str | None = None,
                          weekday: int | None = None,
                          day_of_month: int | None = None) -> str:
    """Create a recurring job that runs `prompt` as a full agent turn on its
    own chat thread — use when the user asks for something on a cadence
    ("every day at 5pm", "each week", "run X nightly", "remind me every").
    Confirm the cadence with the user before creating; a one-off question is
    NOT a job. All times are WIB.

    Args:
        name: Short job name — also becomes the thread's sidebar title.
        prompt: The instruction the agent runs each slot, e.g. "scan my
            holdings for new corporate actions and summarize what changed".
        frequency: "daily" | "weekly" | "monthly".
        run_time: "HH:MM" WIB (default 17:00).
        weekday: weekly only — 0=Mon … 6=Sun.
        day_of_month: monthly only — 1-28 (clamped; no month-end edges).
    """
    uid = _uid(config)
    if uid is None:
        return json.dumps({"error": "no_user"})
    try:
        rt = _parse_time(run_time)
    except ValueError:
        return json.dumps({"error": "invalid_run_time",
                           "detail": "run_time must be HH:MM"})
    try:
        job = await store.create_job(
            uid, name=name, prompt=prompt, frequency=frequency,
            run_time=rt, weekday=weekday, day_of_month=day_of_month)
    except ValueError as exc:
        return json.dumps({"error": "invalid_cadence", "detail": str(exc)})
    return json.dumps(_out(store.job_dict(job)), default=str)


@tool
async def schedule_update(job_id: str, config: RunnableConfig,
                          name: str | None = None,
                          prompt: str | None = None,
                          frequency: str | None = None,
                          run_time: str | None = None,
                          weekday: int | None = None,
                          day_of_month: int | None = None,
                          enabled: bool | None = None) -> str:
    """Rename, rephrase, reschedule, pause or resume one of the user's jobs
    (job_id from schedule_list). Only provided fields change — a frequency
    switch still needs its cadence field (weekday / day_of_month).

    Args:
        job_id: The job's id.
        enabled: False pauses without deleting.
    """
    uid = _uid(config)
    if uid is None:
        return json.dumps({"error": "no_user"})
    fields = {k: v for k, v in {
        "name": name, "prompt": prompt, "frequency": frequency,
        "weekday": weekday, "day_of_month": day_of_month,
        "enabled": enabled}.items() if v is not None}
    if run_time is not None:
        try:
            fields["run_time"] = _parse_time(run_time)
        except ValueError:
            return json.dumps({"error": "invalid_run_time",
                               "detail": "run_time must be HH:MM"})
    if not fields:
        return json.dumps({"error": "nothing_to_update"})
    try:
        job = await store.update_job(uid, job_id, fields)
    except ValueError as exc:
        return json.dumps({"error": "invalid_cadence", "detail": str(exc)})
    if job is None:
        return json.dumps({"error": "not_found"})
    return json.dumps(_out(store.job_dict(job)), default=str)


@tool
async def schedule_delete(job_id: str, config: RunnableConfig) -> str:
    """Delete a scheduled job. Its thread — and every answer it produced —
    stays in the user's history.

    Args:
        job_id: The job's id from schedule_list.
    """
    uid = _uid(config)
    if uid is None:
        return json.dumps({"error": "no_user"})
    if not await store.delete_job(uid, job_id):
        return json.dumps({"error": "not_found"})
    return json.dumps({"deleted": True})
