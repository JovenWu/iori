import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.memory import store
from app.memory.recall import recall_scored
from app.models.memory import Memory
from app.models.user import User
from app.schemas.memory import MemoryListOut, MemorySearchResult

router = APIRouter()


@router.get("", response_model=MemoryListOut)
async def list_memories(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    memories = await store.list_memories(db, current_user.id, limit, offset)
    total = await store.count_memories(db, current_user.id)
    return {"memories": memories, "count": total}


@router.get("/search", response_model=list[MemorySearchResult])
async def search_memories(
    q: str = Query(min_length=1, max_length=500),
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    return await recall_scored(db, current_user.id, q)


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    try:
        parsed = uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid memory id")

    memory = await db.get(Memory, parsed)
    if memory is None or memory.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Memory not found")

    await store.delete_memory(db, parsed, current_user.id)
    return {"detail": "Memory deleted", "memory_id": memory_id}
