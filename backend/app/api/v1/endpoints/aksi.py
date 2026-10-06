"""Aksi Korporasi: holdings, corporate-action checks (SSE), reports, impact."""

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agent.runs import RunLimitError, registry
from app.aksi import impact as impact_mod
from app.aksi import service, store
from app.api import deps
from app.api.sse import sse_response
from app.models.user import User
from app.schemas.aksi import (
    CheckRequest,
    HoldingsIn,
    HoldingsOut,
    ImpactOut,
    ImpactRequest,
    ReportOut,
)
from app.schemas.chat import StopOut

router = APIRouter()


@router.get("/holdings", response_model=HoldingsOut)
async def get_holdings(current_user: User = Depends(deps.get_current_user)):
    return {"holdings": await store.list_holdings(current_user.id)}


@router.put("/holdings", response_model=HoldingsOut)
async def put_holdings(body: HoldingsIn, current_user: User = Depends(deps.get_current_user)):
    await store.replace_holdings(current_user.id, [h.model_dump() for h in body.holdings])
    return {"holdings": await store.list_holdings(current_user.id)}


@router.post("/check")
async def start_check(body: CheckRequest, current_user: User = Depends(deps.get_current_user)):
    """Start a check — detached like a chat turn; GET /check/stream replays."""
    key = service.run_key(current_user.id)
    async with registry.thread_lock(key):
        await registry.stop_and_wait(key)  # a new check supersedes a live one
        try:
            run = registry.start_run(current_user.id, key)
        except RunLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc))
        run.task = asyncio.create_task(
            service.run_check(run, current_user.id, body.as_of, body.symbols, body.budget)
        )
    return sse_response(run)


@router.get("/check/stream")
async def check_stream(last_seq: int = Query(0, ge=0),
                       current_user: User = Depends(deps.get_current_user)):
    run = registry.get(service.run_key(current_user.id))
    if run is None:
        raise HTTPException(status_code=404, detail="No check for this user")
    return sse_response(run, last_seq)


@router.post("/check/stop", response_model=StopOut)
async def stop_check(current_user: User = Depends(deps.get_current_user)):
    stopped = await registry.stop_and_wait(service.run_key(current_user.id))
    return {"detail": "Stop requested" if stopped else "No active check", "stopped": stopped}


@router.get("/reports/latest", response_model=ReportOut)
async def latest_report(mode: str | None = Query(None, pattern="^(live|replay)$"),
                        current_user: User = Depends(deps.get_current_user)):
    report = await store.latest_report(current_user.id, mode)
    if report is None:
        raise HTTPException(status_code=404, detail="No report yet")
    return report


@router.get("/reports/{report_id}", response_model=ReportOut)
async def get_report(report_id: uuid.UUID, current_user: User = Depends(deps.get_current_user)):
    report = await store.get_report(current_user.id, str(report_id))
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.post("/impact", response_model=ImpactOut)
async def impact(body: ImpactRequest, current_user: User = Depends(deps.get_current_user)):
    return await impact_mod.impact(body.symbol, body.shares, body.as_of)
