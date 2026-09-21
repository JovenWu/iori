"""Sectors cache administration — hit/credit stats and manual flush.

The cache is global market data shared across users; these endpoints are
authenticated but not per-user scoped.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.api import deps
from app.models.user import User
from app.sectors import cache

router = APIRouter()


@router.get("/cache/stats")
async def sectors_cache_stats(
    _: User = Depends(deps.get_current_user),
) -> Any:
    return await cache.cache_stats()


@router.delete("/cache")
async def sectors_cache_flush(
    _: User = Depends(deps.get_current_user),
) -> Any:
    return {"cleared": await cache.cache_clear()}
