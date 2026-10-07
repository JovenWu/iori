from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class CreditBudget(TimeStampedBase):
    """Singleton row — global Sectors credit counter.

    `spent` is the reserved upstream cost across all users. Reservations
    happen before a fetch (`spent + cost <= cap`), then refund when the
    response was a non-billable status — so `spent` tracks real consumption
    and the cap can never overshoot.
    """

    __tablename__ = "credit_budget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    spent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
