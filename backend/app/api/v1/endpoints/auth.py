import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core import security
from app.core.config import settings
from app.core.ratelimit import limiter
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, Token, TokenPayload

router = APIRouter()


def _token_response(user: User) -> dict[str, Any]:
    access_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    version = user.token_version or 0
    return {
        "access_token": security.create_access_token(user.id, version),
        "refresh_token": security.create_refresh_token(user.id, version),
        "token_type": "bearer",
        "expires_at": (datetime.now(timezone.utc) + access_expires).isoformat(),
        "user": user,
    }


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    """Authenticate the env-configured account; auto-provisions the user row
    on first successful login. There is no registration endpoint."""
    valid = secrets.compare_digest(
        body.username, settings.APP_USERNAME
    ) and secrets.compare_digest(body.password, settings.APP_PASSWORD)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    result = await db.execute(
        select(User).where(User.username == settings.APP_USERNAME)
    )
    user = result.scalars().first()
    if user is None:
        user = User(username=settings.APP_USERNAME, is_active=True)
        db.add(user)
        await db.flush()
        await db.refresh(user)
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    return _token_response(user)


@router.post("/refresh", response_model=Token)
@limiter.limit("20/minute")
async def refresh(
    request: Request,
    body: RefreshRequest,
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    invalid = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Could not validate refresh token",
    )
    try:
        payload = jwt.decode(
            body.refresh_token,
            settings.SECRET_KEY,
            algorithms=[security.ALGORITHM],
        )
        token_data = TokenPayload(**payload)
    except (JWTError, ValueError):
        raise invalid

    if token_data.type != "refresh" or token_data.sub is None:
        raise invalid
    try:
        user_id = int(token_data.sub)
    except (TypeError, ValueError):
        raise invalid

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if (token_data.ver or 0) != (user.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Refresh token has been revoked",
        )

    return _token_response(user)


@router.post("/logout")
async def logout(
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    """Revoke every outstanding token by bumping the user's token_version."""
    current_user.token_version = (current_user.token_version or 0) + 1
    db.add(current_user)
    await db.flush()
    return {"detail": "Logged out", "revoked": True}
