import uuid
from datetime import datetime

from pydantic import BaseModel


class MemoryOut(BaseModel):
    id: uuid.UUID
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemoryListOut(BaseModel):
    memories: list[MemoryOut]
    count: int


class MemorySearchResult(BaseModel):
    memory: MemoryOut
    vector_score: float
    rerank_score: float
