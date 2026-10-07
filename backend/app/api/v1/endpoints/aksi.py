"""Aksi Korporasi: holdings, corporate-action checks (SSE), reports, impact."""

import asyncio
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.agent.runs import RunLimitError, registry
from app.aksi import impact as impact_mod
from app.aksi import service, store
from app.api import deps
from app.api.sse import sse_response
from app.core.ratelimit import limiter
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
async def get_holdings(user_id: int = Depends(deps.get_current_user_id)):
    return {"holdings": await store.list_holdings(user_id)}


@router.put("/holdings", response_model=HoldingsOut)
async def put_holdings(body: HoldingsIn, user_id: int = Depends(deps.get_current_user_id)):
    await store.replace_holdings(user_id, [h.model_dump() for h in body.holdings])
    return {"holdings": await store.list_holdings(user_id)}


@router.post("/check")
@limiter.limit("10/minute")  # every check burns Sectors credits
async def start_check(request: Request, body: CheckRequest,
                      user_id: int = Depends(deps.get_current_user_id)):
    """Start a check — detached like a chat turn; GET /check/stream replays."""
    key = service.run_key(user_id)
    async with registry.thread_lock(key):
        await registry.stop_and_wait(key)  # a new check supersedes a live one
        try:
            run = registry.start_run(user_id, key)
        except RunLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc))
        run.task = asyncio.create_task(
            service.run_check(run, user_id, body.as_of, body.symbols, body.budget)
        )
    return sse_response(run)


@router.get("/check/stream")
async def check_stream(last_seq: int = Query(0, ge=0),
                       user_id: int = Depends(deps.get_current_user_id)):
    run = registry.get(service.run_key(user_id))
    if run is None:
        raise HTTPException(status_code=404, detail="No check for this user")
    return sse_response(run, last_seq)


@router.post("/check/stop", response_model=StopOut)
async def stop_check(user_id: int = Depends(deps.get_current_user_id)):
    key = service.run_key(user_id)
    # Serialized with start_check — a racing stop must not kill a just-started run.
    async with registry.thread_lock(key):
        stopped = await registry.stop_and_wait(key)
    return {"detail": "Stop requested" if stopped else "No active check", "stopped": stopped}


@router.get("/reports/latest", response_model=ReportOut)
async def latest_report(mode: str | None = Query(None, pattern="^(live|replay)$"),
                        as_of: date | None = Query(None),
                        user_id: int = Depends(deps.get_current_user_id)):
    report = await store.latest_report(user_id, mode, as_of)
    if report is None:
        raise HTTPException(status_code=404, detail="No report yet")
    return report


@router.get("/reports/{report_id}", response_model=ReportOut)
async def get_report(report_id: uuid.UUID, user_id: int = Depends(deps.get_current_user_id)):
    report = await store.get_report(user_id, str(report_id))
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.post("/impact", response_model=ImpactOut)
@limiter.limit("30/minute")  # each call spends Sectors credits
async def impact(request: Request, body: ImpactRequest,
                 user_id: int = Depends(deps.get_current_user_id)):
    return await impact_mod.impact(body.symbol, body.shares, body.as_of)
