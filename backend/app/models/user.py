from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class User(TimeStampedBase):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    # None for the env-provisioned account — it authenticates against
    # APP_USERNAME/APP_PASSWORD instead of a stored hash.
    hashed_password: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Embedded in every JWT as `ver`; bumping it (logout) revokes all of the
    # user's outstanding access and refresh tokens.
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
