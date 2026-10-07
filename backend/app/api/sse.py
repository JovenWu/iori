"""Server-sent events over a detached run's replay buffer (chat + aksi)."""

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.agent.runs import AgentRun

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

# A silent connection gets a comment line this often — keeps proxies and
# browsers from timing the stream out while a run is alive but idle.
_HEARTBEAT_S = 25.0


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


async def event_stream(run: AgentRun, queue: asyncio.Queue) -> AsyncIterator[str]:
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), _HEARTBEAT_S)
            except asyncio.TimeoutError:
                if run.done:
                    break  # finished without a sentinel — nothing to drain
                yield ": hb\n\n"
                continue
            if event is None:
                break
            yield sse(event)
    finally:
        run.unsubscribe(queue)


def sse_response(run: AgentRun, last_seq: int = 0) -> StreamingResponse:
    queue = run.subscribe(last_seq)
    if queue is None:
        raise HTTPException(
            status_code=429, detail="Too many open streams on this run"
        )
    return StreamingResponse(
        event_stream(run, queue), media_type="text/event-stream", headers=SSE_HEADERS
    )
