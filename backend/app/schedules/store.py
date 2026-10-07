"""Persistence for scheduled jobs (own sessions, like the aksi store)."""

import uuid
from datetime import datetime, time

from sqlalchemy import select

from app.db.session import async_session_maker
from app.models.scheduled_job import ScheduledJob
from app.models.thread import Thread
from app.schedules.due import due_now, next_run_at, normalize_cadence


async def create_job(user_id: int, *, name: str, prompt: str, frequency: str,
                     run_time: time | None, weekday: int | None,
                     day_of_month: int | None) -> ScheduledJob:
    freq, wd, dom = normalize_cadence(frequency, weekday, day_of_month)
    async with async_session_maker() as db:
        # The job's transcript thread is born with it — the name doubles as
        # the sidebar title.
        thread = Thread(user_id=user_id, title=name)
        db.add(thread)
        job = ScheduledJob(
            user_id=user_id, name=name, prompt=prompt, frequency=freq,
            run_time=run_time or time(17, 0), weekday=wd, day_of_month=dom,
            thread=thread,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


async def list_jobs(user_id: int) -> list[ScheduledJob]:
    async with async_session_maker() as db:
        rows = (await db.execute(
            select(ScheduledJob)
            .where(ScheduledJob.user_id == user_id)
            .order_by(ScheduledJob.created_at)
        )).scalars().all()
    return list(rows)


async def get_job(user_id: int, job_id: uuid.UUID | str) -> ScheduledJob | None:
    async with async_session_maker() as db:
        job = await db.get(ScheduledJob, job_id)
    if job is None or job.user_id != user_id:
        return None
    return job


async def update_job(user_id: int, job_id: uuid.UUID | str,
                     fields: dict) -> ScheduledJob | None:
    """Partial update — cadence fields are re-normalized against the merged
    result so e.g. daily→weekly still requires a weekday."""
    async with async_session_maker() as db:
        job = await db.get(ScheduledJob, job_id)
        if job is None or job.user_id != user_id:
            return None
        for key in ("name", "prompt", "enabled", "run_time"):
            if key in fields:
                setattr(job, key, fields[key])
        if {"frequency", "weekday", "day_of_month"} & fields.keys():
            freq, wd, dom = normalize_cadence(
                fields.get("frequency", job.frequency),
                fields.get("weekday", job.weekday),
                fields.get("day_of_month", job.day_of_month),
            )
            job.frequency, job.weekday, job.day_of_month = freq, wd, dom
        await db.commit()
        await db.refresh(job)
        return job


async def delete_job(user_id: int, job_id: uuid.UUID | str) -> bool:
    """Deletes the job only — the thread (and its answers) survives."""
    async with async_session_maker() as db:
        job = await db.get(ScheduledJob, job_id)
        if job is None or job.user_id != user_id:
            return False
        await db.delete(job)
        await db.commit()
        return True


async def scheduled_thread_ids(user_id: int) -> set[uuid.UUID]:
    """Thread ids owned by this user's jobs — used to flag them in the
    thread list so the UI can mark them as scheduled."""
    async with async_session_maker() as db:
        rows = (await db.execute(
            select(ScheduledJob.thread_id)
            .where(ScheduledJob.user_id == user_id)
        )).scalars().all()
    return set(rows)


async def due_jobs(now: datetime | None = None) -> list[ScheduledJob]:
    """Enabled jobs whose slot arrived and hasn't fired — oldest first."""
    async with async_session_maker() as db:
        rows = (await db.execute(
            select(ScheduledJob)
            .where(ScheduledJob.enabled.is_(True))
            .order_by(ScheduledJob.created_at)
        )).scalars().all()
    return [
        j for j in rows
        if due_now(frequency=j.frequency, run_time=j.run_time,
                   weekday=j.weekday, day_of_month=j.day_of_month,
                   last_run_at=j.last_run_at, enabled=j.enabled, now=now)
    ]


async def stamp_last_run(job_id: uuid.UUID, when: datetime) -> None:
    async with async_session_maker() as db:
        job = await db.get(ScheduledJob, job_id)
        if job is not None:
            job.last_run_at = when
            await db.commit()


def job_dict(job: ScheduledJob) -> dict:
    nxt = next_run_at(frequency=job.frequency, run_time=job.run_time,
                      weekday=job.weekday, day_of_month=job.day_of_month)
    return {
        "id": str(job.id), "name": job.name, "prompt": job.prompt,
        "frequency": job.frequency,
        "run_time": job.run_time.strftime("%H:%M"),
        "weekday": job.weekday, "day_of_month": job.day_of_month,
        "enabled": job.enabled, "thread_id": str(job.thread_id),
        "last_run_at": job.last_run_at,
        "next_run_at": nxt,
        "created_at": job.created_at,
    }
