import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    thread_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=8000)


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


class ChatMessageOut(BaseModel):
    role: str
    content: str


class ThreadDetailOut(ThreadOut):
    messages: list[ChatMessageOut]


class StopOut(BaseModel):
    detail: str
    stopped: bool
