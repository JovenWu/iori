"""Chat + threads: SSE streaming (detached runs), resume, stop, CRUD."""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import service
from app.agent.runs import RunLimitError, registry
from app.api import deps
from app.api.sse import sse_response
from app.models.thread import Thread
from app.models.user import User
from app.schedules import store as schedules_store
from app.schemas.chat import (
    ChatStreamRequest,
    StopOut,
    ThreadDetailOut,
    ThreadListOut,
    ThreadOut,
    ThreadUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _thread_dict(t: Thread, sched_ids: set[uuid.UUID]) -> dict:
    scheduled = t.id in sched_ids
    # Unread = scheduled thread with output newer than the user's last open.
    # Never opened → unread once a run has produced its first answer.
    if t.last_read_at is not None:
        unread = t.updated_at > t.last_read_at
    else:
        unread = t.first_answer_preview is not None
    return {
        **ThreadOut.model_validate(t).model_dump(),
        "scheduled": scheduled,
        "unread": scheduled and unread,
    }


@router.post("/chat/stream")
async def chat_stream(
    body: ChatStreamRequest,
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    """Start a new turn. The run is detached: generation continues if the
    client disconnects; GET /threads/{id}/stream replays missed events."""
    # Resolve (or create) the thread first so we can key the mutation lock.
    try:
        thread = await service.get_or_create_thread(
            db, current_user.id, body.thread_id, body.message
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Thread not found")
    tid = str(thread.id)
    if body.thread_id is not None:
        await service.mark_thread_read(db, thread)

    async with service.thread_lock(tid):
        await registry.stop_and_wait(tid)  # a new turn supersedes any live run
        try:
            run = registry.start_run(current_user.id, tid)
        except RunLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc))
        run.task = asyncio.create_task(
            service.run_turn(run, current_user.id, tid, body.message, body.lang)
        )
        # Buffered — subscribers replay it; lets clients stop a fresh thread's
        # first run before done/stopped carries the id. started_at anchors the
        # client's live timer so remounts don't zero it.
        run.emit(
            "started", {"thread_id": tid, "started_at": int(time.time() * 1000)}
        )

    return sse_response(run)


@router.get("/threads/{thread_id}/stream")
async def thread_stream(
    thread_id: uuid.UUID,
    last_seq: int = Query(0, ge=0),
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    """Re-attach to a run (or replay a finished one within its linger window)."""
    thread = await service.get_thread(db, current_user.id, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    run = registry.get(str(thread_id))
    if run is None:
        raise HTTPException(status_code=404, detail="No run for this thread")
    return sse_response(run, last_seq)


@router.post("/threads/{thread_id}/stop", response_model=StopOut)
async def stop_thread(
    thread_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    thread = await service.get_thread(db, current_user.id, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    tid = str(thread_id)
    # Serialized with chat_stream/delete_thread — a racing stop must not kill
    # a just-started run that hasn't emitted `started` yet.
    async with service.thread_lock(tid):
        stopped = await registry.stop_and_wait(tid)
    return {"detail": "Stop requested" if stopped else "No active run", "stopped": stopped}


@router.get("/threads", response_model=ThreadListOut)
async def list_threads(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    before: tuple[datetime, uuid.UUID] | None = None
    if cursor:
        raw_updated, sep, raw_id = cursor.rpartition("_")
        try:
            if not sep:
                raise ValueError
            before = (datetime.fromisoformat(raw_updated), uuid.UUID(raw_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor")
    threads, next_cursor, total, starred = await service.list_threads(
        db, current_user.id, limit=limit, before=before
    )
    sched_ids = await schedules_store.scheduled_thread_ids(current_user.id)
    return {
        "threads": [_thread_dict(t, sched_ids) for t in threads],
        "next_cursor": next_cursor,
        "total": total,
        "starred": [_thread_dict(t, sched_ids) for t in starred],
    }


@router.get("/threads/{thread_id}", response_model=ThreadDetailOut)
async def get_thread(
    thread_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    thread = await service.get_thread(db, current_user.id, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    messages = await service.get_thread_messages(thread_id)
    run = registry.get(str(thread_id))
    sched_ids = await schedules_store.scheduled_thread_ids(current_user.id)
    out = _thread_dict(thread, sched_ids)
    await service.mark_thread_read(db, thread)
    return {
        **out,
        "messages": messages,
        "has_active_run": run is not None and not run.done,
    }


@router.patch("/threads/{thread_id}", response_model=ThreadOut)
async def update_thread(
    thread_id: uuid.UUID,
    body: ThreadUpdateRequest,
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    thread = await service.update_thread(
        db, current_user.id, thread_id, title=body.title, starred=body.starred
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    sched_ids = await schedules_store.scheduled_thread_ids(current_user.id)
    return _thread_dict(thread, sched_ids)


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    tid = str(thread_id)
    async with service.thread_lock(tid):
        await registry.stop_and_wait(tid)
        deleted = await service.delete_thread(db, current_user.id, thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"detail": "Thread deleted", "thread_id": tid}
