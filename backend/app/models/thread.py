import uuid

from sqlalchemy import UUID, Boolean, ForeignKey, Integer, String
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
