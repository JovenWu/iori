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
    # Live viewers per run are few (one or two tabs); beyond that a pile of
    # dead connections would each queue every event — cap them outright.
    SUBSCRIBER_MAX = 8

    def __init__(self, thread_id: str, user_id: int):
        self.run_id = uuid.uuid4().hex
        self.thread_id = thread_id
        self.user_id = user_id
        self.task: asyncio.Task | None = None
        self.done = False
        self.stop_requested = False
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
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A subscriber that isn't draining (dead connection) — drop
                # it; it can re-attach with last_seq and replay the buffer.
                self._subscribers.discard(queue)

    def subscribe(self, last_seq: int = 0) -> asyncio.Queue | None:
        """Queue prefilled with every event after `last_seq`; ends with None.
        Returns None when the run already has SUBSCRIBER_MAX subscribers."""
        if len(self._subscribers) >= self.SUBSCRIBER_MAX:
            return None
        # Bounded: buffer depth plus slack for the end sentinel.
        queue: asyncio.Queue = asyncio.Queue(
            maxsize=settings.STREAM_RUN_BUFFER_MAX + 8)
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
            raise RunLimitError(
                "Previous run is still stopping; retry in a moment"
                if existing.stop_requested
                else "Thread already has an active run"
            )
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
        run.stop_requested = True
        if run.task is not None:
            run.task.cancel()
        return run

    async def stop_and_wait(self, thread_id: str, timeout: float = 10.0) -> bool:
        """Cancel the run's producer and wait for it to settle so a new turn
        starts on a quiesced checkpoint. On timeout the run stays active until
        the task actually exits — a superseding turn can never race a zombie
        producer writing checkpoints on the same thread."""
        run = self.request_stop(thread_id)
        if run is None:
            return False
        task = run.task
        if task is None:
            if not run.done:
                self.finish(run)
            return True
        # The run closes when the producer actually exits — covers both slow
        # cancellation and a task that died before reaching its try/finally.
        task.add_done_callback(lambda _t, r=run: self.finish(r))
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout)
        except asyncio.TimeoutError:
            pass  # still stopping — the run stays active until the task exits
        except asyncio.CancelledError:
            if not task.done():
                raise  # our caller was cancelled — do not supersede mid-flight
        except Exception:
            pass  # the producer surfaced an error and finished itself
        if task.done() and not run.done:
            self.finish(run)
        return True

    def finish(self, run: AgentRun) -> None:
        """Mark done, release subscribers, and schedule linger eviction."""
        if run.done:
            return
        run.done = True
        run.finished_at = time.monotonic()
        for queue in list(run._subscribers):  # snapshot — discard mutates
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                # Full queue means the reader is dead — drop it rather than
                # block the finish path.
                run._subscribers.discard(queue)
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
        lock = self._locks.get(thread_id)
        # Skip a held lock — and one with queued waiters (asyncio exposes them
        # as `_waiters`), which would otherwise split the critical section.
        if (
            lock is not None
            and not lock.locked()
            and not getattr(lock, "_waiters", None)
        ):
            del self._locks[thread_id]


registry = RunRegistry()
