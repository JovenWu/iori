"""ScheduledJob CRUD + due_jobs — store owns its sessions."""

import pytest
import pytest_asyncio

from app.models.thread import Thread
from app.schedules import store

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def _bind(bound_session_maker):
    yield


async def test_create_job_makes_backing_thread(db, _bind, user):
    job = await store.create_job(
        user.id, name="Nightly scan", prompt="check my holdings",
        frequency="daily", run_time=None, weekday=None, day_of_month=None)
    assert job.thread_id is not None
    thread = await db.get(Thread, job.thread_id)
    assert thread is not None and thread.title == "Nightly scan"
    assert job.run_time.hour == 17  # default


async def test_list_and_get_scoped_to_user(db, _bind, user):
    from app.models.user import User
    other = User(username="other")
    db.add(other)
    await db.commit()
    job = await store.create_job(
        user.id, name="mine", prompt="p", frequency="daily",
        run_time=None, weekday=None, day_of_month=None)
    assert [j.id for j in await store.list_jobs(user.id)] == [job.id]
    assert await store.list_jobs(other.id) == []
    assert await store.get_job(other.id, job.id) is None  # not yours


async def test_update_job_partial_and_cadence(db, _bind, user):
    job = await store.create_job(
        user.id, name="a", prompt="p", frequency="daily",
        run_time=None, weekday=None, day_of_month=None)
    job = await store.update_job(user.id, job.id, {"name": "b", "enabled": False})
    assert job.name == "b" and job.enabled is False
    job = await store.update_job(
        user.id, job.id, {"frequency": "weekly", "weekday": 4})
    assert (job.frequency, job.weekday) == ("weekly", 4)
    with pytest.raises(ValueError):
        await store.update_job(user.id, job.id, {"frequency": "monthly"})


async def test_delete_job_keeps_thread(db, _bind, user):
    job = await store.create_job(
        user.id, name="tmp", prompt="p", frequency="daily",
        run_time=None, weekday=None, day_of_month=None)
    assert await store.delete_job(user.id, job.id) is True
    assert await store.delete_job(user.id, job.id) is False
    assert await db.get(Thread, job.thread_id) is not None


async def test_due_jobs_filters(db, _bind, user):
    from datetime import datetime, time
    from app.schedules.due import WIB
    due = await store.create_job(
        user.id, name="due", prompt="p", frequency="daily",
        run_time=time(9, 0), weekday=None, day_of_month=None)
    await store.create_job(
        user.id, name="notdue", prompt="p", frequency="daily",
        run_time=time(23, 59), weekday=None, day_of_month=None)
    now = datetime(2026, 10, 7, 18, 0, tzinfo=WIB)
    ids = [j.id for j in await store.due_jobs(now)]
    assert ids == [due.id]
    # Once stamped past the slot, no longer due.
    await store.stamp_last_run(due.id, now)
    assert await store.due_jobs(now) == []


async def test_scheduled_thread_ids(db, _bind, user):
    job = await store.create_job(
        user.id, name="flag", prompt="p", frequency="daily",
        run_time=None, weekday=None, day_of_month=None)
    assert await store.scheduled_thread_ids(user.id) == {job.thread_id}
    assert await store.scheduled_thread_ids(999) == set()


async def test_mark_thread_read_does_not_bump(db, _bind, user):
    """Marking read must not reorder Recent — updated_at is pinned."""
    from app.agent import service

    job = await store.create_job(
        user.id, name="r", prompt="p", frequency="daily",
        run_time=None, weekday=None, day_of_month=None)
    thread = await db.get(Thread, job.thread_id)
    before = thread.updated_at
    await service.mark_thread_read(db, thread)
    thread = await db.get(Thread, job.thread_id)
    assert thread.last_read_at is not None
    assert thread.updated_at == before


async def test_update_name_syncs_thread_title(db, _bind, user):
    job = await store.create_job(
        user.id, name="a", prompt="p", frequency="daily",
        run_time=None, weekday=None, day_of_month=None)
    before = (await db.get(Thread, job.thread_id)).updated_at
    await store.update_job(user.id, job.id, {"name": "Renamed"})
    thread = await db.get(Thread, job.thread_id)
    assert thread.title == "Renamed"
    assert thread.updated_at == before  # a rename isn't activity
    assert await store.job_for_thread(job.thread_id) is not None
    plain = Thread(user_id=user.id)
    db.add(plain)
    await db.commit()
    assert await store.job_for_thread(plain.id) is None


async def test_job_dict_has_next_run(db, _bind, user):
    job = await store.create_job(
        user.id, name="d", prompt="p", frequency="daily",
        run_time=None, weekday=None, day_of_month=None)
    out = store.job_dict(job)
    assert out["run_time"] == "17:00" and out["next_run_at"] is not None
    assert out["thread_id"] == str(job.thread_id)
