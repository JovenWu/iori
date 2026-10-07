import uuid
from datetime import datetime

from sqlalchemy import UUID, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class Thread(TimeStampedBase):
    """A conversation thread owned by a user."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String)
    starred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Denormalized preview of the first assistant answer so the thread list
    # never deserializes full checkpoints.
    first_answer_preview: Mapped[str | None] = mapped_column(String)
    # Last time the user opened this thread — drives the unread marker on
    # scheduled-job threads (a run finished while they weren't looking).
    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
