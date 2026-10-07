import uuid
from datetime import datetime, time

from sqlalchemy import (
    UUID,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import TimeStampedBase
from app.models.thread import Thread


class ScheduledJob(TimeStampedBase):
    """A named recurring prompt — fires a normal agent turn on its thread."""

    __tablename__ = "scheduled_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[str] = mapped_column(String(7), nullable=False)
    # Wall-clock WIB — the tz is fixed in v1.
    run_time: Mapped[time] = mapped_column(
        Time, nullable=False, default=lambda: time(17, 0)
    )
    weekday: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    day_of_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # The job's transcript — deleting the job keeps the thread; deleting the
    # thread removes the job (it has nowhere to write).
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    thread: Mapped[Thread] = relationship()
    # Stamped at fire time — a failed/skipped slot never retries.
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
