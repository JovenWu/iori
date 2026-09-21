from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class SectorsCache(TimeStampedBase):
    """Global, permanent response cache for the Sectors API.

    Market data is identical for every user, so the cache is shared. Entries
    never expire — staleness is computed on read from `freshness` +
    `fetched_at` and the agent decides whether to pay for a refresh. `hits` x
    `credits` counts the upstream cost avoided.
    """

    __tablename__ = "sectors_cache"

    # sha256 of endpoint + canonical params — the request IS the identity.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    freshness: Mapped[str] = mapped_column(String(16), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
