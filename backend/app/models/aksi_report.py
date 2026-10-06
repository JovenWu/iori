import uuid
from datetime import date

from sqlalchemy import UUID, Date, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class AksiReport(TimeStampedBase):
    """One corporate-action check. Events are appended as each finishes, so a
    stopped run keeps its partial results."""

    __tablename__ = "aksi_reports"
    __table_args__ = (Index("ix_aksi_reports_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(8), nullable=False)  # live | replay
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # running|done|stopped|error
    holdings_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    events: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    credits_spent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
