import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    thread_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=8000)
    # App language setting — drives the reply language in the system prompt.
    lang: Literal["en", "id"] = "en"


class ThreadUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    starred: bool | None = None


class ThreadOut(BaseModel):
    id: uuid.UUID
    title: str | None
    starred: bool
    first_answer_preview: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ThreadListOut(BaseModel):
    threads: list[ThreadOut]
    next_cursor: str | None = None
    total: int
    # All of the user's starred threads — populated on page one only, so
    # favorites render even when they'd fall outside the loaded pages.
    starred: list[ThreadOut] = []


class ChartSpecOut(BaseModel):
    """Normalized chart spec — built by app/sectors/charts.py, `anchor`
    stripped before it reaches the API."""
    id: str
    tool: str
    view: str
    kind: str
    title: str
    x: dict[str, Any]
    series: list[dict[str, Any]]
    data: list[dict[str, Any]]
    fetched_at: str
    format: str | None = None


class ToolCallOut(BaseModel):
    name: str
    args: dict[str, Any] = {}


class ChatMessageOut(BaseModel):
    role: str
    content: str
    # Reasoning summary the model produced for this turn, if any — the live
    # stream reports it as `reasoning` events.
    reasoning: str | None = None
    # Tool calls that ran in this turn (history reconstruction — the live
    # stream reports them as `tool` events instead).
    tools: list[ToolCallOut] = []
    charts: list[ChartSpecOut] = []


class ThreadDetailOut(ThreadOut):
    messages: list[ChatMessageOut]
    # A detached run is still generating for this thread — the client should
    # reattach via GET /threads/{id}/stream rather than showing history only.
    has_active_run: bool = False


class StopOut(BaseModel):
    detail: str
    stopped: bool
