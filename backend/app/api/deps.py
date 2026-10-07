from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.db.session import async_session_maker
from app.models.user import User
from app.schemas.auth import TokenPayload

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/token"
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Request-scoped session; commits on success, rolls back on error."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _user_for_token(db: AsyncSession, token: str) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Could not validate credentials",
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (JWTError, ValidationError, ValueError):
        raise credentials_error

    if token_data.type != "access" or token_data.sub is None:
        raise credentials_error

    try:
        user_id = int(token_data.sub)
    except (TypeError, ValueError):
        raise credentials_error

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    # A token whose `ver` lags the user's token_version was revoked by logout.
    if (token_data.ver or 0) != (user.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token has been revoked",
        )
    return user


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(reusable_oauth2),
) -> User:
    return await _user_for_token(db, token)


async def get_current_user_id(
    token: str = Depends(reusable_oauth2),
) -> int:
    """Auth for long-lived SSE endpoints — the session closes before the
    response starts streaming, so a stream never pins a pooled connection."""
    async with async_session_maker() as db:
        user = await _user_for_token(db, token)
        return user.id
