"""Aksi Korporasi: holdings, corporate-action checks (SSE), reports, impact."""

from fastapi import APIRouter, Depends

from app.aksi import store
from app.api import deps
from app.models.user import User
from app.schemas.aksi import HoldingsIn, HoldingsOut

router = APIRouter()


@router.get("/holdings", response_model=HoldingsOut)
async def get_holdings(current_user: User = Depends(deps.get_current_user)):
    return {"holdings": await store.list_holdings(current_user.id)}


@router.put("/holdings", response_model=HoldingsOut)
async def put_holdings(body: HoldingsIn, current_user: User = Depends(deps.get_current_user)):
    await store.replace_holdings(current_user.id, [h.model_dump() for h in body.holdings])
    return {"holdings": await store.list_holdings(current_user.id)}
