"""Scheduled jobs — recurring prompts that fire normal agent turns."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.agent import scheduler
from app.api import deps
from app.models.user import User
from app.schedules import store
from app.schemas.schedule import ScheduleIn, ScheduleOut, SchedulePatch

router = APIRouter()


@router.get("/schedules", response_model=list[ScheduleOut])
async def list_schedules(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    return [store.job_dict(j) for j in await store.list_jobs(current_user.id)]


@router.post("/schedules", response_model=ScheduleOut)
async def create_schedule(
    body: ScheduleIn,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    try:
        job = await store.create_job(
            current_user.id, name=body.name, prompt=body.prompt,
            frequency=body.frequency,
            run_time=body.run_time,
            weekday=body.weekday, day_of_month=body.day_of_month,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return store.job_dict(job)


@router.patch("/schedules/{job_id}", response_model=ScheduleOut)
async def update_schedule(
    job_id: uuid.UUID,
    body: SchedulePatch,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    try:
        job = await store.update_job(
            current_user.id, job_id, body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return store.job_dict(job)


@router.delete("/schedules/{job_id}")
async def delete_schedule(
    job_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    if not await store.delete_job(current_user.id, job_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"detail": "Schedule deleted", "job_id": str(job_id)}


@router.post("/schedules/{job_id}/run")
async def run_schedule_now(
    job_id: uuid.UUID,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """Fire the job immediately — a demo/debug affordance. The scheduled
    slot still fires normally (manual runs don't consume it)."""
    job = await store.get_job(current_user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    status = await scheduler.fire_job(job)
    return {"status": status, "job": store.job_dict(job)}
