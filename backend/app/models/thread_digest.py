import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import UUID, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class ThreadDigest(TimeStampedBase):
    """Compact searchable gist of one thread — the basis of cross-thread recall."""

    __tablename__ = "thread_digests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String)
    digest: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stale_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_turn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def content(self) -> str:
        """Alias so shared rerank/RRF helpers (which read `.content`) work."""
        return self.digest
