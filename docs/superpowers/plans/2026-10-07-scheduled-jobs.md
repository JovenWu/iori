# Scheduled Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** User-named recurring prompts (daily/weekly/monthly at a WIB time) that fire a normal `service.run_turn` agent turn on a dedicated thread — ChatGPT/Claude-style scheduled tasks.

**Architecture:** A `scheduled_jobs` table (1:1 with `threads`) plus a `due` module of pure slot math, a `store` module of session-owning CRUD (aksi pattern), an asyncio worker `app/agent/scheduler.py` in the FastAPI lifespan that stamps `last_run_at` and launches `run_turn` on due jobs, a `/api/v1/schedules` REST surface, and `schedule_*` chat tools registered into `AGENT_TOOLS`. The thread bump, live reattach, replay buffer, and notifier all come free because the run keys on the job's thread id.

**Tech Stack:** FastAPI, SQLAlchemy async + Alembic, LangGraph run registry, pytest + httpx ASGITransport; Next.js + Tailwind + shadcn/ui + zustand on the frontend.

**Spec:** `docs/superpowers/specs/2026-10-07-scheduled-checks-design.md`

## Global Constraints

- Backend runs Python 3.10 — no `datetime.UTC` (use `timezone.utc`), no 3.11+ syntax.
- Never output buy/sell/hold/exercise advice anywhere (POJK 6/2026).
- No Sectors calls in scheduler tests — mock `service.run_turn`; never pass `refresh=True` to `app.sectors.client.get`.
- Commit style: lowercase `phase 16: short description`. No agent trailers/attribution.
- All job times are **WIB** (`Asia/Jakarta`) — `run_time` is a naive wall-clock `time`, `last_run_at`/`next_run_at` are tz-aware.
- `monthly.day_of_month` is clamped 1–28 (February never misses).
- Validation: `weekly` requires `weekday` (0=Mon…6=Sun), `monthly` requires `day_of_month`, `daily` requires neither.
- Stamp `last_run_at` BEFORE firing — an error/skipped slot never retries until the next slot.
- Test commands run inside docker: `docker compose exec backend python -m pytest ...`. The test DB is `sectors_agent_test` (conftest).

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/schedules/__init__.py` | empty package marker |
| `backend/app/schedules/due.py` | pure slot math — `due_now`, `next_run_at`, `normalize_cadence`, `WIB` |
| `backend/app/schedules/store.py` | session-owning CRUD + `due_jobs` + `stamp_last_run` + `job_dict` serializer |
| `backend/app/schedules/tools.py` | `schedule_list/create/update/delete` agent tools |
| `backend/app/models/scheduled_job.py` | `ScheduledJob` ORM model (`__tablename__ = "scheduled_jobs"`) |
| `backend/app/schemas/schedule.py` | `ScheduleIn`, `SchedulePatch`, `ScheduleOut` pydantic schemas |
| `backend/app/api/v1/endpoints/schedules.py` | REST surface GET/POST/PATCH/DELETE + `POST /{id}/run` |
| `backend/app/agent/scheduler.py` | `fire_job`, `tick`, `scheduler_loop` — the asyncio worker |
| `backend/alembic/versions/20261007_0900_c3f1a9e27d04_scheduled_jobs.py` | migration |
| `backend/app/agent/service.py` | `run_turn` gains `scheduled` flag → HumanMessage `additional_kwargs` |
| `backend/app/agent/nodes.py` | lang hint skipped when `lang` is falsy (scheduled turns pass `lang=None`) |
| `backend/app/agent/tools_node.py` + `router.py` | register tools + route recurring-task prompts |
| `backend/app/main.py`, `backend/app/core/config.py` | lifespan task + `SCHEDULER_*` settings |
| `frontend/app/(chat)/schedules/page.tsx`, `frontend/components/schedules/schedules-view.tsx` | the page |
| `frontend/lib/api.ts`, `frontend/components/sidebar-threads.tsx`, `frontend/components/chat-messages.tsx`, `frontend/lib/stores/chat.ts` | client + sidebar + "Scheduled" marker |

---

### Task 1: Due math — `app/schedules/due.py`

Pure functions, no DB — fully testable.

**Files:**
- Create: `backend/app/schedules/__init__.py` (empty)
- Create: `backend/app/schedules/due.py`
- Test: `backend/tests/test_schedules_due.py`

**Interfaces:**
- Produces:
  - `WIB = ZoneInfo("Asia/Jakarta")`
  - `due_now(frequency, run_time, weekday, day_of_month, last_run_at, enabled=True, now=None) -> bool`
  - `next_run_at(frequency, run_time, weekday, day_of_month, now=None) -> datetime | None`
  - `normalize_cadence(frequency, weekday, day_of_month) -> tuple[str, int | None, int | None]` (raises `ValueError`)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_schedules_due.py
"""Slot math for scheduled jobs — WIB wall-clock, dedup via last_run_at."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.schedules.due import WIB, due_now, next_run_at, normalize_cadence

T1700 = time(17, 0)
# Wednesday 2026-10-07 (weekday() == 2) at 18:00 WIB.
NOW = datetime(2026, 10, 7, 18, 0, tzinfo=ZoneInfo("Asia/Jakarta"))


def _due(**kw):
    kw.setdefault("run_time", T1700)
    kw.setdefault("weekday", None)
    kw.setdefault("day_of_month", None)
    kw.setdefault("last_run_at", None)
    kw.setdefault("now", NOW)
    return due_now(**kw)


def test_daily_due_after_slot():
    assert _due(frequency="daily") is True


def test_daily_not_due_before_slot():
    early = NOW.replace(hour=16, minute=0)
    assert _due(frequency="daily", now=early) is False


def test_daily_not_due_when_already_ran():
    ran = datetime(2026, 10, 7, 17, 5, tzinfo=WIB)
    assert _due(frequency="daily", last_run_at=ran) is False
    # Yesterday's run doesn't block today's slot.
    yesterday = datetime(2026, 10, 6, 17, 5, tzinfo=WIB)
    assert _due(frequency="daily", last_run_at=yesterday) is True


def test_weekly_only_on_matching_weekday():
    assert _due(frequency="weekly", weekday=2) is True   # Wed == Wed
    assert _due(frequency="weekly", weekday=0) is False  # Mon != Wed


def test_monthly_only_on_day_of_month():
    assert _due(frequency="monthly", day_of_month=7) is True
    assert _due(frequency="monthly", day_of_month=8) is False


def test_disabled_never_due():
    assert _due(frequency="daily", enabled=False) is False


def test_next_run_daily_today_then_tomorrow():
    before = NOW.replace(hour=9)
    nxt = next_run_at("daily", T1700, None, None, now=before)
    assert (nxt.day, nxt.hour) == (7, 17)          # today 17:00
    nxt = next_run_at("daily", T1700, None, None, now=NOW)
    assert (nxt.day, nxt.hour) == (8, 17)          # tomorrow 17:00


def test_next_run_weekly_skips_to_matching_day():
    nxt = next_run_at("weekly", T1700, 0, None, now=NOW)  # next Mon
    assert (nxt.day, nxt.weekday(), nxt.hour) == (12, 0, 17)
    # Same-day-but-later still counts.
    before = NOW.replace(hour=9)
    nxt = next_run_at("weekly", T1700, 2, None, now=before)
    assert nxt.day == 7


def test_next_run_monthly_this_then_next_month():
    before = NOW.replace(day=1)
    nxt = next_run_at("monthly", T1700, None, 7, now=before)
    assert (nxt.month, nxt.day) == (10, 7)
    nxt = next_run_at("monthly", T1700, None, 7, now=NOW)
    assert (nxt.month, nxt.day) == (11, 7)


def test_next_run_monthly_clamps_28_in_february():
    feb = datetime(2026, 2, 20, 9, 0, tzinfo=WIB)
    nxt = next_run_at("monthly", T1700, None, 31, now=feb)
    assert (nxt.month, nxt.day) == (2, 28)


def test_normalize_cadence():
    assert normalize_cadence("daily", 3, 9) == ("daily", None, None)
    assert normalize_cadence("weekly", 4, 9) == ("weekly", 4, None)
    assert normalize_cadence("monthly", 3, 31) == ("monthly", None, 28)
    with pytest.raises(ValueError):
        normalize_cadence("weekly", None, None)
    with pytest.raises(ValueError):
        normalize_cadence("monthly", None, None)
    with pytest.raises(ValueError):
        normalize_cadence("hourly", None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend python -m pytest tests/test_schedules_due.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.schedules'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/schedules/__init__.py
```

(empty file)

```python
# backend/app/schedules/due.py
"""Slot math for scheduled jobs — pure functions over WIB wall-clock time."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
_FREQUENCIES = {"daily", "weekly", "monthly"}
# Monthly jobs clamp to the 28th — February never misses a slot.
_MAX_MONTH_DAY = 28


def _slot_on(day: date, run_time: time) -> datetime:
    return datetime.combine(day, run_time, tzinfo=WIB)


def due_now(*, frequency: str, run_time: time, weekday: int | None,
            day_of_month: int | None, last_run_at: datetime | None,
            enabled: bool = True, now: datetime | None = None) -> bool:
    """True when this slot has arrived and hasn't already fired. `last_run_at`
    is stamped at fire time, so a failed/skipped slot never retries."""
    now = now or datetime.now(WIB)
    if not enabled:
        return False
    slot = None
    if frequency == "daily":
        slot = _slot_on(now.date(), run_time)
    elif frequency == "weekly":
        if weekday is not None and now.weekday() == weekday:
            slot = _slot_on(now.date(), run_time)
    elif frequency == "monthly":
        if day_of_month is not None and now.day == day_of_month:
            slot = _slot_on(now.date(), run_time)
    if slot is None or now < slot:
        return False
    return last_run_at is None or last_run_at < slot


def _next_month(now: datetime) -> tuple[int, int]:
    return (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)


def next_run_at(*, frequency: str, run_time: time, weekday: int | None,
                day_of_month: int | None,
                now: datetime | None = None) -> datetime | None:
    """The next future slot in WIB — independent of last_run_at, so a missed
    or manual run still shows the real next occurrence."""
    now = now or datetime.now(WIB)
    if frequency == "daily":
        today = _slot_on(now.date(), run_time)
        return today if now < today else _slot_on(
            now.date() + timedelta(days=1), run_time)
    if frequency == "weekly" and weekday is not None:
        for delta in range(8):
            slot = _slot_on(now.date() + timedelta(days=delta), run_time)
            if slot.weekday() == weekday and now < slot:
                return slot
        return None
    if frequency == "monthly" and day_of_month is not None:
        day = min(day_of_month, _MAX_MONTH_DAY)
        this_month = _slot_on(date(now.year, now.month, day), run_time)
        if now < this_month:
            return this_month
        year, month = _next_month(now)
        return _slot_on(date(year, month, day), run_time)
    return None


def normalize_cadence(frequency: str, weekday: int | None,
                      day_of_month: int | None,
                      ) -> tuple[str, int | None, int | None]:
    """Canonical (frequency, weekday, day_of_month) — irrelevant fields are
    stripped, day_of_month clamps to 28. Raises ValueError on bad input."""
    if frequency == "daily":
        return "daily", None, None
    if frequency == "weekly":
        if weekday is None or not 0 <= weekday <= 6:
            raise ValueError("weekly requires weekday 0-6 (0=Mon)")
        return "weekly", weekday, None
    if frequency == "monthly":
        if day_of_month is None:
            raise ValueError("monthly requires day_of_month")
        return "monthly", None, max(1, min(_MAX_MONTH_DAY, day_of_month))
    raise ValueError("frequency must be daily, weekly or monthly")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend python -m pytest tests/test_schedules_due.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/schedules/__init__.py backend/app/schedules/due.py backend/tests/test_schedules_due.py
git commit -m "phase 16: scheduled job slot math — WIB due/next-run helpers"
```

---

### Task 2: Model + migration + store

**Files:**
- Create: `backend/app/models/scheduled_job.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/schedules/store.py`
- Create: `backend/alembic/versions/20261007_0900_c3f1a9e27d04_scheduled_jobs.py`
- Test: `backend/tests/test_schedules_store.py`

**Interfaces:**
- Consumes: `due.due_now`, `due.next_run_at`, `due.normalize_cadence` (Task 1)
- Produces:
  - `ScheduledJob` ORM (cols per spec §2)
  - `create_job(user_id, *, name, prompt, frequency, run_time, weekday, day_of_month) -> ScheduledJob` — creates the backing `Thread` (title=name)
  - `list_jobs(user_id) -> list[ScheduledJob]`
  - `get_job(user_id, job_id) -> ScheduledJob | None`
  - `update_job(user_id, job_id, fields: dict) -> ScheduledJob | None` (raises `ValueError` on bad cadence)
  - `delete_job(user_id, job_id) -> bool` — thread survives
  - `due_jobs(now=None) -> list[ScheduledJob]` — enabled + `due_now`
  - `stamp_last_run(job_id, when) -> None`
  - `job_dict(job) -> dict` — JSON-ready incl. `next_run_at`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_schedules_store.py
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


async def test_job_dict_has_next_run(db, _bind, user):
    job = await store.create_job(
        user.id, name="d", prompt="p", frequency="daily",
        run_time=None, weekday=None, day_of_month=None)
    out = store.job_dict(job)
    assert out["run_time"] == "17:00" and out["next_run_at"] is not None
    assert out["thread_id"] == str(job.thread_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend python -m pytest tests/test_schedules_store.py -v`
Expected: FAIL — `No module named 'app.schedules.store'` / `ScheduledJob` missing

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/scheduled_job.py
import uuid
from datetime import datetime, time

from sqlalchemy import (
    UUID,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class ScheduledJob(TimeStampedBase):
    """A named recurring prompt — fires a normal agent turn on its thread."""

    __tablename__ = "scheduled_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[str] = mapped_column(String(7), nullable=False)
    # Wall-clock WIB — the tz is fixed in v1.
    run_time: Mapped[time] = mapped_column(
        Time, nullable=False, default=lambda: time(17, 0)
    )
    weekday: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    day_of_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # The job's transcript — deleting the job keeps the thread; deleting the
    # thread removes the job (it has nowhere to write).
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # Stamped at fire time — a failed/skipped slot never retries.
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

```python
# backend/app/models/__init__.py — add to imports and __all__
from app.models.scheduled_job import ScheduledJob
# __all__: ..., "ScheduledJob", ...
```

```python
# backend/app/schedules/store.py
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
```

The `ScheduledJob.thread` relationship needs a `relationship` — add to the model:

```python
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.thread import Thread

# inside ScheduledJob, after thread_id column:
    thread: Mapped[Thread] = relationship()
```

```python
# backend/alembic/versions/20261007_0900_c3f1a9e27d04_scheduled_jobs.py
"""scheduled_jobs

Revision ID: c3f1a9e27d04
Revises: b4e1a7c9d2f3
Create Date: 2026-10-07 09:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3f1a9e27d04'
down_revision: Union[str, None] = 'b4e1a7c9d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('scheduled_jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('frequency', sa.String(length=7), nullable=False),
    sa.Column('run_time', sa.Time(), nullable=False),
    sa.Column('weekday', sa.SmallInteger(), nullable=True),
    sa.Column('day_of_month', sa.SmallInteger(), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('thread_id', sa.UUID(), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('thread_id', name='uq_scheduled_jobs_thread_id')
    )
    op.create_index(op.f('ix_scheduled_jobs_user_id'), 'scheduled_jobs',
                    ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_scheduled_jobs_user_id'), table_name='scheduled_jobs')
    op.drop_table('scheduled_jobs')
```

- [ ] **Step 4: Run tests + apply migration**

Run:
```bash
docker compose exec backend python -m pytest tests/test_schedules_store.py -v
docker compose exec backend alembic upgrade head
```
Expected: 6 passed; migration applies `scheduled_jobs`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/scheduled_job.py backend/app/models/__init__.py backend/app/schedules/store.py backend/alembic/versions/20261007_0900_c3f1a9e27d04_scheduled_jobs.py backend/tests/test_schedules_store.py
git commit -m "phase 16: scheduled_jobs model, migration and store"
```

---

### Task 3: REST API — `/api/v1/schedules`

**Files:**
- Create: `backend/app/schemas/schedule.py`
- Create: `backend/app/api/v1/endpoints/schedules.py`
- Modify: `backend/app/api/v1/api.py`
- Test: `backend/tests/test_schedules_api.py`

**Interfaces:**
- Consumes: `store.*`, `scheduler.fire_job` (imported lazily inside the run endpoint to keep Task 4 independent — `from app.agent import scheduler` at module top is also fine; scheduler module has no import-time side effects)
- Produces: routes `GET/POST /schedules`, `PATCH/DELETE /schedules/{id}`, `POST /schedules/{id}/run`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_schedules_api.py
"""Schedules REST — CRUD, validation, auth scoping, run-now."""

import pytest

from app.core.config import settings

URL = "/api/v1/schedules"


async def _login(client) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.APP_USERNAME,
              "password": settings.APP_PASSWORD},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_list_get(client):
    h = await _login(client)
    resp = await client.post(URL, headers=h, json={
        "name": "Nightly scan", "prompt": "check holdings", "frequency": "daily"})
    assert resp.status_code == 200, resp.text
    job = resp.json()
    assert job["run_time"] == "17:00:00" and job["enabled"] is True
    assert job["next_run_at"] is not None and job["thread_id"]
    # The backing thread is a real thread.
    thread = await client.get(f"/api/v1/threads/{job['thread_id']}", headers=h)
    assert thread.status_code == 200 and thread.json()["title"] == "Nightly scan"
    listed = (await client.get(URL, headers=h)).json()
    assert [j["id"] for j in listed] == [job["id"]]


@pytest.mark.asyncio
async def test_validation(client):
    h = await _login(client)
    no_weekday = await client.post(URL, headers=h, json={
        "name": "w", "prompt": "p", "frequency": "weekly"})
    no_dom = await client.post(URL, headers=h, json={
        "name": "m", "prompt": "p", "frequency": "monthly"})
    bad_freq = await client.post(URL, headers=h, json={
        "name": "x", "prompt": "p", "frequency": "hourly"})
    assert [no_weekday.status_code, no_dom.status_code,
            bad_freq.status_code] == [422, 422, 422]


@pytest.mark.asyncio
async def test_patch_and_delete_keeps_thread(client):
    h = await _login(client)
    job = (await client.post(URL, headers=h, json={
        "name": "a", "prompt": "p", "frequency": "daily"})).json()
    patched = await client.patch(f"{URL}/{job['id']}", headers=h, json={
        "name": "b", "enabled": False, "frequency": "weekly", "weekday": 1})
    assert patched.status_code == 200
    assert patched.json()["frequency"] == "weekly" and patched.json()["weekday"] == 1
    bad = await client.patch(f"{URL}/{job['id']}", headers=h,
                             json={"frequency": "monthly"})
    assert bad.status_code == 422
    tid = job["thread_id"]
    assert (await client.delete(f"{URL}/{job['id']}", headers=h)).status_code == 200
    assert (await client.get(URL, headers=h)).json() == []
    # Thread survives the job.
    assert (await client.get(f"/api/v1/threads/{tid}", headers=h)).status_code == 200


@pytest.mark.asyncio
async def test_run_now(client, bound_session_maker, monkeypatch):
    from app.agent import service
    from app.agent.runs import registry

    fired = []

    async def fake_run_turn(run, user_id, thread_id, user_msg, lang="en",
                            scheduled=False):
        fired.append((user_id, thread_id, user_msg, scheduled))
        run.emit("done", {"answer": "ok", "thread_id": thread_id})
        registry.finish(run)

    monkeypatch.setattr(service, "run_turn", fake_run_turn)

    h = await _login(client)
    job = (await client.post(URL, headers=h, json={
        "name": "fire", "prompt": "do it now", "frequency": "daily"})).json()
    resp = await client.post(f"{URL}/{job['id']}/run", headers=h)
    assert resp.status_code == 200 and resp.json()["status"] == "fired"
    # The producer task is detached — poll briefly for it to run.
    for _ in range(50):
        if fired:
            break
        await asyncio.sleep(0.02)
    assert fired and fired[0][2] == "do it now" and fired[0][3] is True
    assert fired[0][1] == job["thread_id"]
    again = await client.post(f"{URL}/{job['id']}/run", headers=h)
    assert again.json()["status"] in ("fired", "skipped", "busy")


@pytest.mark.asyncio
async def test_requires_auth(client):
    assert (await client.get(URL)).status_code == 401
    assert (await client.post(URL, json={})).status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend python -m pytest tests/test_schedules_api.py -v`
Expected: FAIL — 404 on `/api/v1/schedules` (route not registered yet; the run-now test also needs Task 4's `scheduler.fire_job` + `scheduled` kwarg — implement Task 4's `app/agent/scheduler.py` and the `run_turn` signature change **first** if running strictly in order, or accept this test staying red until Task 4 lands. Recommended: implement Tasks 3 and 4's code, then run both test files.)

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/schemas/schedule.py
import uuid
from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=8000)
    frequency: Literal["daily", "weekly", "monthly"]
    # "HH:MM" WIB — defaults to 17:00 server-side.
    run_time: time | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)

    @model_validator(mode="after")
    def _cadence(self):
        if self.frequency == "weekly" and self.weekday is None:
            raise ValueError("weekly requires weekday (0=Mon … 6=Sun)")
        if self.frequency == "monthly" and self.day_of_month is None:
            raise ValueError("monthly requires day_of_month")
        return self


class SchedulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    prompt: str | None = Field(default=None, min_length=1, max_length=8000)
    frequency: Literal["daily", "weekly", "monthly"] | None = None
    run_time: time | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    enabled: bool | None = None


class ScheduleOut(BaseModel):
    id: uuid.UUID
    name: str
    prompt: str
    frequency: str
    run_time: time
    weekday: int | None
    day_of_month: int | None
    enabled: bool
    thread_id: uuid.UUID
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime
```

```python
# backend/app/api/v1/endpoints/schedules.py
"""Scheduled jobs — recurring prompts that fire normal agent turns."""

import uuid
from datetime import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.agent import scheduler
from app.api import deps
from app.models.user import User
from app.schedules import store
from app.schemas.schedule import ScheduleIn, ScheduleOut, SchedulePatch

router = APIRouter()


@router.get("/schedules", response_model=list[ScheduleOut])
async def list_schedules(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    return [store.job_dict(j) for j in await store.list_jobs(current_user.id)]


@router.post("/schedules", response_model=ScheduleOut)
async def create_schedule(
    body: ScheduleIn,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    try:
        job = await store.create_job(
            current_user.id, name=body.name, prompt=body.prompt,
            frequency=body.frequency,
            run_time=body.run_time or time(17, 0),
            weekday=body.weekday, day_of_month=body.day_of_month,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return store.job_dict(job)


@router.patch("/schedules/{job_id}", response_model=ScheduleOut)
async def update_schedule(
    job_id: uuid.UUID,
    body: SchedulePatch,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    try:
        job = await store.update_job(
            current_user.id, job_id, body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return store.job_dict(job)


@router.delete("/schedules/{job_id}")
async def delete_schedule(
    job_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    if not await store.delete_job(current_user.id, job_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"detail": "Schedule deleted", "job_id": str(job_id)}


@router.post("/schedules/{job_id}/run")
async def run_schedule_now(
    job_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """Fire the job immediately — a demo/debug affordance. The scheduled
    slot still fires normally (manual runs don't consume it)."""
    job = await store.get_job(current_user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    status = await scheduler.fire_job(job)
    return {"status": status, "job": store.job_dict(job)}
```

```python
# backend/app/api/v1/api.py — add
from app.api.v1.endpoints import aksi, auth, chat, memory, schedules, sectors, users
api_router.include_router(schedules.router, prefix="/schedules", tags=["schedules"])
```

- [ ] **Step 4: Commit (tests still red until Task 4 lands the scheduler module)**

```bash
git add backend/app/schemas/schedule.py backend/app/api/v1/endpoints/schedules.py backend/app/api/v1/api.py backend/tests/test_schedules_api.py
git commit -m "phase 16: /schedules REST — CRUD, validation, run-now"
```

---

### Task 4: Scheduler worker + `run_turn` scheduled flag + lang fix

**Files:**
- Create: `backend/app/agent/scheduler.py`
- Modify: `backend/app/core/config.py` (add `SCHEDULER_*` settings)
- Modify: `backend/app/main.py` (lifespan start/cancel)
- Modify: `backend/app/agent/service.py` (`run_turn` gains `lang=None` tolerance + `scheduled` flag; `get_thread_messages` emits it)
- Modify: `backend/app/agent/nodes.py` (skip lang hint when falsy)
- Modify: `backend/app/schemas/chat.py` (`ChatMessageOut.scheduled`)
- Test: `backend/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `store.due_jobs`, `store.stamp_last_run`, `registry`, `service.run_turn`
- Produces:
  - `fire_job(job) -> str` — `"fired" | "skipped" | "busy"`
  - `tick(now=None) -> int` — count fired
  - `scheduler_loop() -> None` — forever task
  - `run_turn(run, user_id, thread_id, user_msg, lang="en", scheduled=False)`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_scheduler.py
"""Scheduler worker — due jobs fire a normal agent turn on their thread."""

import asyncio
from datetime import datetime, time

import pytest
import pytest_asyncio

from app.agent import scheduler, service
from app.agent.runs import registry
from app.schedules import store
from app.schedules.due import WIB

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 7, 18, 0, tzinfo=WIB)


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
    live = registry.start_run(user.id, str(job.thread_id))  # user mid-chat
    fired = await scheduler.tick(NOW)
    assert fired == 0 and calls == []
    job = await store.get_job(user.id, job.id)
    assert job.last_run_at is not None  # slot consumed — no retry
    registry.finish(live)


async def test_not_due_jobs_do_not_fire(db, _bind, user, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "run_turn", _fake_turn(calls))
    await store.create_job(
        user.id, name="n", prompt="p", frequency="daily",
        run_time=time(23, 59), weekday=None, day_of_month=None)
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
    # Occupy the first job's thread — it "skips", the second still fires.
    live = registry.start_run(user.id, str(bad.thread_id))
    fired = await scheduler.tick(NOW)
    assert fired == 1
    await _drain(calls)
    assert calls[0]["thread_id"] == str(good.thread_id)
    registry.finish(live)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend python -m pytest tests/test_scheduler.py -v`
Expected: FAIL — `No module named 'app.agent.scheduler'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agent/scheduler.py
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
```

```python
# backend/app/core/config.py — append to Settings (near STREAM_* block):
    # Scheduled jobs worker — recurring prompts fired as normal agent turns.
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TICK_SECONDS: int = 60
    SCHEDULER_MAX_PER_TICK: int = 5
```

```python
# backend/app/main.py — inside lifespan, after sectors_client.init_client():
    from app.agent import scheduler

    scheduler_task = (
        asyncio.create_task(scheduler.scheduler_loop())
        if settings.SCHEDULER_ENABLED
        else None
    )
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        await sectors_client.close_client()
        ...  # rest unchanged
```

```python
# backend/app/agent/service.py — signature + HumanMessage flag:
async def run_turn(
    run: AgentRun, user_id: int, thread_id: str, user_msg: str,
    lang: str | None = "en", scheduled: bool = False,
) -> None:
    ...
    # inside the astream call:
    {"messages": [HumanMessage(
        content=user_msg,
        # Scheduled turns are marked so history can badge them.
        additional_kwargs={"scheduled": True} if scheduled else {},
    )]},

# in get_thread_messages — user entry:
        if isinstance(m.content, str):
            entry = {"role": "user", "content": m.content}
            if m.additional_kwargs.get("scheduled"):
                entry["scheduled"] = True
            entries.append((i, entry))
```

```python
# backend/app/agent/nodes.py — in _compose_system, replace the lang hint:
    lang = (config.get("configurable") or {}).get("lang")
    # Scheduled turns pass lang=None — leave the default "match the user's
    # message" rule instead of forcing a language.
    if lang and (hint := _LANG_HINTS.get(str(lang))):
        parts.append(hint)
```

```python
# backend/app/schemas/chat.py — ChatMessageOut:
    # True when the turn was fired by a scheduled job, not typed by the user.
    scheduled: bool = False
```

- [ ] **Step 4: Run tests**

Run:
```bash
docker compose exec backend python -m pytest tests/test_scheduler.py tests/test_schedules_api.py -v
```
Expected: all pass (scheduler 5 + api 5).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/scheduler.py backend/app/core/config.py backend/app/main.py backend/app/agent/service.py backend/app/agent/nodes.py backend/app/schemas/chat.py backend/tests/test_scheduler.py
git commit -m "phase 16: scheduler worker fires due jobs as agent turns"
```

---

### Task 5: Chat tools — `schedule_*` + router registration

**Files:**
- Create: `backend/app/schedules/tools.py`
- Modify: `backend/app/agent/tools_node.py` (register into `AGENT_TOOLS`)
- Modify: `backend/app/agent/router.py` (recurring-task phrasing in `sectors_data`)
- Test: `backend/tests/test_schedule_tools.py`

**Interfaces:**
- Consumes: `store.*`, `_uid` pattern from `app/aksi/tools.py` (duplicated — module-local by convention)
- Produces: `schedule_list`, `schedule_create`, `schedule_update`, `schedule_delete` `@tool`s

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_schedule_tools.py
"""schedule_* tools — the agent manages its own recurring jobs."""

import json

import pytest
import pytest_asyncio

from app.agent import tools_node
from app.models.thread import Thread
from app.schedules.tools import (
    schedule_create,
    schedule_delete,
    schedule_list,
    schedule_update,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def _bind(bound_session_maker):
    yield


def _cfg(user) -> dict:
    return {"configurable": {"user_id": user.id}}


async def test_create_list_update_delete_roundtrip(db, _bind, user):
    cfg = _cfg(user)
    out = json.loads(await schedule_create.ainvoke(
        {"name": "Nightly aksi scan", "prompt": "check my holdings",
         "frequency": "daily", "run_time": "17:00"}, config=cfg))
    assert "job" in out, out
    job = out["job"]
    assert job["next_run_at"] is not None
    thread = await db.get(Thread, job["thread_id"])
    assert thread is not None and thread.title == "Nightly aksi scan"

    listed = json.loads(await schedule_list.ainvoke({}, config=cfg))
    assert [j["id"] for j in listed["jobs"]] == [job["id"]]

    out = json.loads(await schedule_update.ainvoke(
        {"job_id": job["id"], "enabled": False, "weekday": 5,
         "frequency": "weekly"}, config=cfg))
    assert out["job"]["enabled"] is False and out["job"]["weekday"] == 5

    out = json.loads(await schedule_delete.ainvoke(
        {"job_id": job["id"]}, config=cfg))
    assert out["deleted"] is True
    assert await db.get(Thread, job["thread_id"]) is not None  # kept


async def test_create_rejects_bad_cadence(db, _bind, user):
    out = json.loads(await schedule_create.ainvoke(
        {"name": "x", "prompt": "p", "frequency": "weekly"}, config=_cfg(user)))
    assert out["error"] == "invalid_cadence"
    out = json.loads(await schedule_create.ainvoke(
        {"name": "x", "prompt": "p", "frequency": "daily",
         "run_time": "25:99"}, config=_cfg(user)))
    assert out["error"] == "invalid_run_time"


async def test_tools_registered():
    names = {t.name for t in tools_node.AGENT_TOOLS}
    assert {"schedule_list", "schedule_create",
            "schedule_update", "schedule_delete"} <= names


async def test_schedule_tools_need_user(db, _bind):
    out = json.loads(await schedule_list.ainvoke(
        {}, config={"configurable": {}}))
    assert out["error"] == "no_user"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend python -m pytest tests/test_schedule_tools.py -v`
Expected: FAIL — `No module named 'app.schedules.tools'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/schedules/tools.py
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
```

```python
# backend/app/agent/tools_node.py — extend imports + AGENT_TOOLS:
from app.schedules.tools import (
    schedule_create,
    schedule_delete,
    schedule_list,
    schedule_update,
)
AGENT_TOOLS = [*TOOLS, compute, aksi_impact, aksi_check, aksi_report,
               aksi_reports, holdings_list, holdings_save, holdings_remove,
               schedule_list, schedule_create, schedule_update, schedule_delete]
```

```python
# backend/app/agent/router.py — extend sectors_data description:
    "sectors_data": (
        "IDX market data questions answerable with a few lookups — prices, "
        "screening, company or subsector reports, rankings, broker activity, "
        "foreign flow, filings, suspensions, corporate actions, listing "
        "performance, market news, mining companies/sites/production, and "
        "commodity prices or trade. Also creating or managing scheduled/"
        "recurring tasks — 'remind me', 'every day', 'each week', 'run X "
        "nightly'."
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend python -m pytest tests/test_schedule_tools.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/schedules/tools.py backend/app/agent/tools_node.py backend/app/agent/router.py backend/tests/test_schedule_tools.py
git commit -m "phase 16: schedule_* agent tools — the agent manages its own jobs"
```

---

### Task 6: Frontend — `/schedules` page + sidebar + "Scheduled" marker

**Files:**
- Modify: `frontend/lib/api.ts` (types + 5 functions; `ChatMessage.scheduled`)
- Create: `frontend/app/(chat)/schedules/page.tsx`
- Create: `frontend/components/schedules/schedules-view.tsx`
- Modify: `frontend/components/sidebar-threads.tsx` (menu item, `TimerIcon`)
- Modify: `frontend/components/chat-messages.tsx` (`scheduled` badge on `UserBubble`)
- Modify: `frontend/lib/stores/chat.ts` (`toMessages` passes `scheduled`)

**Interfaces:**
- Consumes: `GET/POST/PATCH/DELETE /api/v1/schedules`, `POST /{id}/run`; `ChatMessage.scheduled` from Task 4
- Produces: `ScheduleJob` type; `listSchedules`, `createSchedule`, `updateSchedule`, `deleteSchedule`, `runScheduleNow`

- [ ] **Step 1: API client additions** — append to `frontend/lib/api.ts`:

```ts
export type ScheduleJob = {
  id: string;
  name: string;
  prompt: string;
  frequency: "daily" | "weekly" | "monthly";
  run_time: string;            // "HH:MM:SS"
  weekday: number | null;      // 0=Mon … 6=Sun (weekly)
  day_of_month: number | null; // 1-28 (monthly)
  enabled: boolean;
  thread_id: string;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
};

export type ScheduleInput = {
  name: string;
  prompt: string;
  frequency: "daily" | "weekly" | "monthly";
  run_time?: string | null;    // "HH:MM"
  weekday?: number | null;
  day_of_month?: number | null;
};

export const listSchedules = () => apiFetch<ScheduleJob[]>("/schedules");
export const createSchedule = (body: ScheduleInput) =>
  apiFetch<ScheduleJob>("/schedules", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const updateSchedule = (
  id: string,
  patch: Partial<ScheduleInput & { enabled: boolean }>,
) =>
  apiFetch<ScheduleJob>(`/schedules/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
export const deleteSchedule = (id: string) =>
  apiFetch<{ detail: string }>(`/schedules/${id}`, { method: "DELETE" });
export const runScheduleNow = (id: string) =>
  apiFetch<{ status: string }>(`/schedules/${id}/run`, { method: "POST" });
```

Also add `scheduled?: boolean` to the `ChatMessage` type in the same file.

- [ ] **Step 2: Page + view**

```tsx
// frontend/app/(chat)/schedules/page.tsx
import { SchedulesView } from "@/components/schedules/schedules-view";

export default function SchedulesPage() {
  return <SchedulesView />;
}
```

`frontend/components/schedules/schedules-view.tsx` — a `"use client"` view modeled on `aksi-view.tsx`: header (`SidebarTrigger` + "Schedules" + New button), a list of job cards, and a create/edit `Dialog`. Job card shows: name, cadence chip, prompt excerpt, next run, `Switch` for enabled, Run-now (`PlayIcon`), Edit (`PencilIcon`), Delete (`Trash2Icon`), "Open thread" link to `/threads/{thread_id}`. Required imports: `lucide-react` icons, `@/components/ui/{button,dialog,input,label,switch,textarea,skeleton}`, `next/link`, `sonner` toast, and the api functions. Cadence chip text: `Daily 17:00`, `Mon 09:00`, `Day 15 · 08:00` — a `formatCadence(job)` helper; `run_time` is sliced to 5 chars. Empty state: `TimerIcon` + "No scheduled jobs yet." + hint to ask the agent. The form: name `Input`, prompt `Textarea`, three frequency buttons, weekday select (7 small buttons Mon–Sun) when weekly, day-of-month `Input type=number min=1 max=28` when monthly, `Input type=time` — all local `useState`; submit calls create/update then re-lists; `toast.error` on `ApiError`.

- [ ] **Step 3: Sidebar item** — in `sidebar-threads.tsx`, add after the Aksi `SidebarMenuItem` (keep the badge on Aksi's item — the new item is a sibling inside the same `SidebarMenu`):

```tsx
<SidebarMenuItem>
  <SidebarMenuButton
    asChild
    tooltip="Schedules"
    isActive={pathname === "/schedules"}
    className="h-10 px-4"
  >
    <Link href="/schedules">
      <TimerIcon />
      <span className="group-data-[collapsible=icon]:hidden">
        Schedules
      </span>
    </Link>
  </SidebarMenuButton>
</SidebarMenuItem>
```

Add `TimerIcon` to the lucide-react import.

- [ ] **Step 4: "Scheduled" marker** — three small edits:

```ts
// lib/stores/chat.ts — toMessages():
    role: m.role === "user" ? "user" : "assistant",
    content: m.content,
    scheduled: m.scheduled,
    ...
```

```tsx
// components/chat-messages.tsx — Message type:
  /** The turn was fired by a scheduled job, not typed by the user. */
  scheduled?: boolean;

// UserBubble signature + render:
function UserBubble({ content, scheduled }: { content: string; scheduled?: boolean }) {
  ...
  return (
    <div className="ml-auto w-fit max-w-[85%]">
      {scheduled && (
        <div className="mb-1 flex items-center justify-end gap-1 text-[11px] font-medium text-muted-foreground">
          <TimerIcon className="size-3" />
          Scheduled
        </div>
      )}
      <div className={cn("rounded-2xl rounded-br-md border ...existing bubble classes...")}>
        ...existing content...
      </div>
    </div>
  );

// usage: <UserBubble content={msg.content} scheduled={msg.scheduled} />
```

(Wrap the existing bubble `div` in the new outer `div`; move `ml-auto w-fit max-w-[85%]` to the outer wrapper and keep the bubble's own classes minus those three.)

- [ ] **Step 5: Verify + commit**

```bash
docker compose exec frontend npx tsc --noEmit
docker compose exec frontend npx eslint .
```

```bash
git add frontend/
git commit -m "phase 16: /schedules page + sidebar entry + scheduled marker"
```

---

### Task 7: Full verification + simplify

- [ ] **Step 1: Full backend suite** — `docker compose exec backend python -m pytest tests` — all green (new + existing).

- [ ] **Step 2: Frontend checks** — `docker compose exec frontend npx tsc --noEmit && docker compose exec frontend npx eslint .`

- [ ] **Step 3: Migration applied** — `docker compose exec backend alembic current` shows `c3f1a9e27d04`.

- [ ] **Step 4: Invoke `/code-simplifier`** on the diff (project convention) and apply its refinements, then commit any cleanups as `phase 16: ...`.

- [ ] **Step 5: Smoke the flow** — `curl -X POST localhost:8000/api/v1/schedules` with a due-in-1-minute job, watch the thread appear in `GET /api/v1/threads`, or use `POST /schedules/{id}/run` then `GET /threads/{id}` to see the scheduled turn's messages.

---

## Notes for the executor

- **Spec order matters in `fire_job`:** stamp `last_run_at` BEFORE the lock — a skipped slot (user mid-chat) is consumed, not retried.
- **`run_turn` never raises** — the scheduler doesn't need per-run exception handling beyond the tick-level guard.
- **`update_job` fields dict** uses `model_dump(exclude_unset=True)` from the endpoint and `{k: v for v is not None}` from the tool — `weekday`/`day_of_month` can't be PATCHed to null directly; cadence normalization strips them anyway.
- **Job threads are normal threads** — they show in sidebar/history/rename/delete for free. Thread deletion cascades to the job (FK `ondelete="CASCADE"` on `thread_id`); job deletion leaves the thread (job row holds the FK).
- **`lang=None`** on scheduled turns: `nodes._compose_system` skips the language hint, so the reply follows the prompt's own language.
- **Don't** pass `refresh=True` anywhere; scheduler tests mock `run_turn` — no Sectors calls at all.
