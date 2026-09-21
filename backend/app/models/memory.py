import hashlib
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import UUID, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class Memory(TimeStampedBase):
    """One long-term user fact plus its dense embedding.

    Memories are scoped to the user (not the thread) so facts persist across
    conversations. `hash` enables exact-duplicate checks without an LLM call.
    """

    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    @staticmethod
    def compute_hash(content: str) -> str:
        return hashlib.sha256(content.lower().strip().encode()).hexdigest()
