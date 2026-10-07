"""Scheduler worker — due jobs fire a normal agent turn on their thread."""

import asyncio
from datetime import datetime, time

import pytest
import pytest_asyncio
from sqlalchemy import update

from app.agent import scheduler, service
from app.agent.runs import registry
from app.models.scheduled_job import ScheduledJob
from app.schedules import store
from app.schedules.due import WIB

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 7, 18, 0, tzinfo=WIB)


async def _unstamp(db, *jobs) -> None:
    """Back-date to a pre-stamp row — as if the slot passed with no run."""
    for job in jobs:
        await db.execute(
            update(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .values(last_run_at=None)
        )
    await db.commit()


@pytest_asyncio.fixture
async def _bind(bound_session_maker):
    yield


def _fake_turn(calls: list):
    async def fake_run_turn(run, user_id, thread_id, user_msg, lang="en",
                            scheduled=False):
        calls.append({"thread_id": thread_id, "msg": user_msg,
                      "lang": lang, "scheduled": scheduled})
        run.emit("done", {"answer": "ok", "thread_id": thread_id})
        registry.finish(run)
    return fake_run_turn


async def _drain(calls: list) -> None:
    """Detached run.task needs a loop turn — poll until it appended."""
    for _ in range(50):
        if calls:
            return
        await asyncio.sleep(0.02)


async def test_tick_fires_agent_turn(db, _bind, user, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "run_turn", _fake_turn(calls))
    job = await store.create_job(
        user.id, name="n", prompt="scan my holdings", frequency="daily",
        run_time=time(9, 0), weekday=None, day_of_month=None)
    await _unstamp(db, job)  # created jobs stamp last_run_at — unstamp = missed slot
    fired = await scheduler.tick(NOW)
    assert fired == 1
    await _drain(calls)
    assert calls == [{"thread_id": str(job.thread_id),
                      "msg": "scan my holdings",
                      "lang": None, "scheduled": True}]
    run = registry.get(str(job.thread_id))
    assert run is not None and run.done
    job = await store.get_job(user.id, job.id)
    assert job.last_run_at is not None  # stamped even though mocked


async def test_skip_when_thread_run_live(db, _bind, user, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "run_turn", _fake_turn(calls))
    job = await store.create_job(
        user.id, name="n", prompt="p", frequency="daily",
        run_time=time(9, 0), weekday=None, day_of_month=None)
    await _unstamp(db, job)
    live = registry.start_run(user.id, str(job.thread_id))  # user mid-chat
    fired = await scheduler.tick(NOW)
    assert fired == 0 and calls == []
    job = await store.get_job(user.id, job.id)
    assert job.last_run_at is not None  # slot consumed — no retry
    registry.finish(live)


async def test_not_due_jobs_do_not_fire(db, _bind, user, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "run_turn", _fake_turn(calls))
    job = await store.create_job(
        user.id, name="n", prompt="p", frequency="daily",
        run_time=time(23, 59), weekday=None, day_of_month=None)
    # A job stamped "just ran" doesn't owe yesterday's missed slot.
    await db.execute(
        update(ScheduledJob)
        .where(ScheduledJob.id == job.id)
        .values(last_run_at=NOW)
    )
    await db.commit()
    assert await scheduler.tick(NOW) == 0 and calls == []


async def test_disabled_job_not_fired(db, _bind, user, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "run_turn", _fake_turn(calls))
    job = await store.create_job(
        user.id, name="n", prompt="p", frequency="daily",
        run_time=time(9, 0), weekday=None, day_of_month=None)
    await store.update_job(user.id, job.id, {"enabled": False})
    assert await scheduler.tick(NOW) == 0 and calls == []


async def test_error_in_one_job_does_not_stop_tick(db, _bind, user, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "run_turn", _fake_turn(calls))
    bad = await store.create_job(
        user.id, name="bad", prompt="p", frequency="daily",
        run_time=time(9, 0), weekday=None, day_of_month=None)
    good = await store.create_job(
        user.id, name="good", prompt="p", frequency="daily",
        run_time=time(9, 0), weekday=None, day_of_month=None)
    await _unstamp(db, bad, good)
    # Occupy the first job's thread — it "skips", the second still fires.
    live = registry.start_run(user.id, str(bad.thread_id))
    fired = await scheduler.tick(NOW)
    assert fired == 1
    await _drain(calls)
    assert calls[0]["thread_id"] == str(good.thread_id)
    registry.finish(live)
