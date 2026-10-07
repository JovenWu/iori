import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core import security
from app.core.config import settings
from app.core.ratelimit import limiter
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    Token,
    TokenPayload,
)

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


def _bad_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
    )


async def _login_user(db: AsyncSession, username: str, password: str) -> User:
    """The env-configured account checks env credentials (and auto-provisions
    its row); any other username is a registered account verified against its
    stored bcrypt hash."""
    if username == settings.APP_USERNAME:
        if not secrets.compare_digest(password, settings.APP_PASSWORD):
            raise _bad_credentials()
        result = await db.execute(
            select(User).where(User.username == settings.APP_USERNAME)
        )
        user = result.scalars().first()
        if user is None:
            user = User(username=settings.APP_USERNAME, is_active=True)
            db.add(user)
            await db.flush()
            await db.refresh(user)
    else:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalars().first()
        if (
            user is None
            or user.hashed_password is None
            or not security.verify_password(password, user.hashed_password)
        ):
            raise _bad_credentials()
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


@router.post("/register", response_model=Token)
@limiter.limit("10/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    """Create a username+password account and log it in."""
    if body.username == settings.APP_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is reserved",
        )
    taken = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Username already taken",
    )
    exists = await db.execute(
        select(User.id).where(User.username == body.username)
    )
    if exists.scalar_one_or_none() is not None:
        raise taken
    user = User(
        username=body.username,
        hashed_password=security.hash_password(body.password),
        is_active=True,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        raise taken
    await db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    """Authenticate the env-configured account (auto-provisioned on first
    login) or a registered user against its stored hash."""
    return _token_response(await _login_user(db, body.username, body.password))


@router.post("/token", response_model=Token)
@limiter.limit("10/minute")
async def token(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(deps.get_db),
) -> Any:
    """OAuth2 password flow — the same credentials as /login. Exists so
    Swagger's Authorize button (the OAuth2PasswordBearer tokenUrl) works."""
    return _token_response(await _login_user(db, form.username, form.password))


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
