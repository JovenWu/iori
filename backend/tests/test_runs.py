"""Run registry: replay buffer, subscriber fan-out, caps, stop, linger."""

import asyncio

import pytest

from app.agent.runs import AgentRun, RunLimitError, RunRegistry
from app.core.config import settings


def test_emit_replays_from_last_seq():
    run = AgentRun("t1", 1)
    run.emit("token", "a")
    run.emit("token", "b")
    run.emit("done", {})

    q = run.subscribe(last_seq=1)
    assert q.get_nowait()["data"] == "b"
    assert q.get_nowait()["type"] == "done"

    q_all = run.subscribe(0)
    assert q_all.qsize() == 3


def test_finish_sends_sentinel_and_late_subscriber_gets_full_replay():
    registry = RunRegistry()
    run = AgentRun("t1", 1)
    registry._runs["t1"] = run
    run.emit("token", "x")
    registry.finish(run)

    assert run.done
    q = run.subscribe(0)
    assert q.get_nowait()["data"] == "x"
    assert q.get_nowait() is None  # sentinel


def test_start_run_rejects_active_same_thread():
    registry = RunRegistry()
    registry.start_run(1, "t1")
    with pytest.raises(RunLimitError):
        registry.start_run(1, "t1")


def test_caps(monkeypatch):
    monkeypatch.setattr(settings, "STREAM_MAX_ACTIVE_RUNS_PER_USER", 1)
    registry = RunRegistry()
    registry.start_run(user_id=1, thread_id="t1")
    with pytest.raises(RunLimitError):
        registry.start_run(user_id=1, thread_id="t2")
    # Different user unaffected.
    registry.start_run(user_id=2, thread_id="t2")

    monkeypatch.setattr(settings, "STREAM_MAX_ACTIVE_RUNS", 2)
    registry2 = RunRegistry()
    registry2.start_run(1, "a")
    registry2.start_run(2, "b")
    with pytest.raises(RunLimitError):
        registry2.start_run(3, "c")


@pytest.mark.asyncio
async def test_stop_and_wait_cancels_producer():
    registry = RunRegistry()
    run = registry.start_run(1, "t1")

    async def producer():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            registry.finish(run)
            raise

    run.task = asyncio.create_task(producer())
    await asyncio.sleep(0)  # let the producer reach its try block
    assert await registry.stop_and_wait("t1") is True
    assert run.done


@pytest.mark.asyncio
async def test_linger_eviction(monkeypatch):
    monkeypatch.setattr(settings, "STREAM_RUN_LINGER_SECONDS", 0.01)
    registry = RunRegistry()
    run = registry.start_run(1, "t1")
    registry.finish(run)
    assert registry.get("t1") is run
    await asyncio.sleep(0.05)
    assert registry.get("t1") is None


def test_buffer_overflow_trims_oldest(monkeypatch):
    monkeypatch.setattr(settings, "STREAM_RUN_BUFFER_MAX", 3)
    run = AgentRun("t1", 1)
    for i in range(5):
        run.emit("token", str(i))
    q = run.subscribe(0)
    assert q.qsize() == 3
    assert q.get_nowait()["data"] == "2"
