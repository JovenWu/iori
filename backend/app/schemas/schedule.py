import uuid
from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=8000)
    frequency: Literal["daily", "weekdays", "weekly", "monthly"]
    # "HH:MM" WIB — defaults to 17:00 server-side.
    run_time: time | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)

    @model_validator(mode="after")
    def _cadence(self):
        if self.frequency == "weekly" and self.weekday is None:
            raise ValueError("weekly requires weekday (0=Mon … 6=Sun)")
        if self.frequency == "monthly" and self.day_of_month is None:
            raise ValueError("monthly requires day_of_month")
        return self


class SchedulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    prompt: str | None = Field(default=None, min_length=1, max_length=8000)
    frequency: Literal["daily", "weekdays", "weekly", "monthly"] | None = None
    run_time: time | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    enabled: bool | None = None


class ScheduleOut(BaseModel):
    id: uuid.UUID
    name: str
    prompt: str
    frequency: str
    run_time: time
    weekday: int | None
    day_of_month: int | None
    enabled: bool
    thread_id: uuid.UUID
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime
