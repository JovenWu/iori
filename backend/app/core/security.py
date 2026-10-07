from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import jwt

from app.core.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _create_token(
    subject: Any,
    token_type: str,
    expires_delta: timedelta,
    token_version: int,
) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    claims = {
        "exp": expire,
        "sub": str(subject),
        "type": token_type,
        # Ties the token to the user's token_version; bumping it revokes
        # every previously issued token.
        "ver": token_version,
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(subject: Any, token_version: int = 0) -> str:
    return _create_token(
        subject,
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        token_version,
    )


def create_refresh_token(subject: Any, token_version: int = 0) -> str:
    return _create_token(
        subject,
        "refresh",
        timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES),
        token_version,
    )
