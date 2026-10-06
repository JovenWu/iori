import uuid
from decimal import Decimal

from sqlalchemy import UUID, BigInteger, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class Holding(TimeStampedBase):
    """A stock the user holds — the scope of their corporate-action checks."""

    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_holdings_user_symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(4), nullable=False)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    avg_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
