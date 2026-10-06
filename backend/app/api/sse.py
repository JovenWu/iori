"""Server-sent events over a detached run's replay buffer (chat + aksi)."""

import json
from typing import Any, AsyncIterator

from fastapi.responses import StreamingResponse

from app.agent.runs import AgentRun

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


async def event_stream(run: AgentRun, last_seq: int = 0) -> AsyncIterator[str]:
    queue = run.subscribe(last_seq)
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield sse(event)
    finally:
        run.unsubscribe(queue)


def sse_response(run: AgentRun, last_seq: int = 0) -> StreamingResponse:
    return StreamingResponse(
        event_stream(run, last_seq), media_type="text/event-stream", headers=SSE_HEADERS
    )
