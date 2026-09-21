"""Detached run registry.

A run keeps generating after the HTTP client disconnects. Subscribers get a
seq-numbered replay buffer: a reconnecting client passes the last seq it saw
and receives everything it missed, then live events, then a None sentinel
when the run finishes. Finished runs linger briefly so late readers can
still drain the buffer, then are evicted.

`emit` and `subscribe` are synchronous on purpose — between the buffer
snapshot and the subscriber add there is no await, so no event can fall
through the crack in a single-threaded event loop.
"""

import asyncio
import logging
import time
import uuid
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class RunLimitError(Exception):
    """Raised when a new run would exceed the global or per-user cap."""


class AgentRun:
    def __init__(self, thread_id: str, user_id: int):
        self.run_id = uuid.uuid4().hex
        self.thread_id = thread_id
        self.user_id = user_id
        self.task: asyncio.Task | None = None
        self.done = False
        self.created_at = time.monotonic()
        self.finished_at: float | None = None
        self._seq = 0
        self._buffer: list[tuple[int, dict[str, Any]]] = []
        self._subscribers: set[asyncio.Queue] = set()

    def emit(self, event_type: str, data: Any) -> None:
        self._seq += 1
        event = {"seq": self._seq, "type": event_type, "data": data}
        self._buffer.append((self._seq, event))
        overflow = len(self._buffer) - settings.STREAM_RUN_BUFFER_MAX
        if overflow > 0:
            del self._buffer[:overflow]
        for queue in self._subscribers:
            queue.put_nowait(event)

    def subscribe(self, last_seq: int = 0) -> asyncio.Queue:
        """Queue prefilled with every event after `last_seq`; ends with None."""
        queue: asyncio.Queue = asyncio.Queue()
        for seq, event in self._buffer:
            if seq > last_seq:
                queue.put_nowait(event)
        self._subscribers.add(queue)
        if self.done:
            queue.put_nowait(None)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._evictions: dict[str, asyncio.TimerHandle] = {}

    def thread_lock(self, thread_id: str) -> asyncio.Lock:
        if thread_id not in self._locks:
            self._locks[thread_id] = asyncio.Lock()
        return self._locks[thread_id]

    def get(self, thread_id: str) -> AgentRun | None:
        return self._runs.get(thread_id)

    def active_count(self, user_id: int | None = None) -> int:
        return sum(
            1
            for r in self._runs.values()
            if not r.done and (user_id is None or r.user_id == user_id)
        )

    def start_run(self, user_id: int, thread_id: str) -> AgentRun:
        """Caller must stop any in-flight run for the thread first."""
        existing = self._runs.get(thread_id)
        if existing is not None and not existing.done:
            raise RunLimitError("Thread already has an active run")
        if existing is not None:
            self._remove(thread_id)
        if self.active_count() >= settings.STREAM_MAX_ACTIVE_RUNS:
            raise RunLimitError("Server is at capacity; try again shortly")
        if (
            self.active_count(user_id)
            >= settings.STREAM_MAX_ACTIVE_RUNS_PER_USER
        ):
            raise RunLimitError("Too many concurrent generations")
        run = AgentRun(thread_id, user_id)
        self._runs[thread_id] = run
        return run

    def request_stop(self, thread_id: str) -> AgentRun | None:
        """Signal the producer to stop; partial output is still persisted."""
        run = self._runs.get(thread_id)
        if run is None or run.done:
            return None
        if run.task is not None:
            run.task.cancel()
        return run

    async def stop_and_wait(self, thread_id: str, timeout: float = 10.0) -> bool:
        """Cancel the run's producer and wait for it to settle so a new turn
        starts on a quiesced checkpoint."""
        run = self.request_stop(thread_id)
        if run is None:
            return False
        if run.task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(run.task), timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass
        # A task cancelled before its first step never reaches the producer's
        # try/finally — close the run here so it can't hang.
        if not run.done:
            self.finish(run)
        return True

    def finish(self, run: AgentRun) -> None:
        """Mark done, release subscribers, and schedule linger eviction."""
        if run.done:
            return
        run.done = True
        run.finished_at = time.monotonic()
        for queue in run._subscribers:
            queue.put_nowait(None)
        try:
            handle = asyncio.get_running_loop().call_later(
                settings.STREAM_RUN_LINGER_SECONDS,
                self._remove,
                run.thread_id,
            )
            self._evictions[run.thread_id] = handle
        except RuntimeError:
            self._remove(run.thread_id)  # no running loop (tests/shutdown)

    def _remove(self, thread_id: str) -> None:
        self._runs.pop(thread_id, None)
        handle = self._evictions.pop(thread_id, None)
        if handle is not None:
            handle.cancel()


registry = RunRegistry()
