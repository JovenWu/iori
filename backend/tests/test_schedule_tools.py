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
