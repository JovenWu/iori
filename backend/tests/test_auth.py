"""Auth: login (env + registered users), registration, refresh, revocation."""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/users/me"


async def _login(client) -> dict:
    resp = await client.post(
        LOGIN_URL,
        json={
            "username": settings.APP_USERNAME,
            "password": settings.APP_PASSWORD,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_login_success_returns_token_pair_and_user(client):
    body = await _login(client)
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == settings.APP_USERNAME


@pytest.mark.asyncio
async def test_login_provisions_user_row(client, db):
    await _login(client)
    result = await db.execute(
        select(User).where(User.username == settings.APP_USERNAME)
    )
    user = result.scalars().first()
    assert user is not None
    assert user.is_active is True


@pytest.mark.asyncio
async def test_login_wrong_password_rejected(client):
    resp = await client.post(
        LOGIN_URL,
        json={"username": settings.APP_USERNAME, "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_and_accepts_access_token(client):
    unauth = await client.get(ME_URL)
    assert unauth.status_code in (401, 403)

    body = await _login(client)
    resp = await client.get(
        ME_URL, headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == settings.APP_USERNAME


@pytest.mark.asyncio
async def test_refresh_returns_new_pair(client):
    body = await _login(client)
    resp = await client.post(
        REFRESH_URL, json={"refresh_token": body["refresh_token"]}
    )
    assert resp.status_code == 200
    refreshed = resp.json()
    assert refreshed["access_token"]
    assert refreshed["refresh_token"]


@pytest.mark.asyncio
async def test_refresh_rejects_access_token(client):
    body = await _login(client)
    resp = await client.post(
        REFRESH_URL, json={"refresh_token": body["access_token"]}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_register_creates_user_and_logs_in(client, db):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": "analyst", "password": "spark-2026"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] and body["user"]["username"] == "analyst"

    result = await db.execute(select(User).where(User.username == "analyst"))
    user = result.scalars().first()
    assert user is not None and user.hashed_password
    assert user.hashed_password != "spark-2026"

    login = await client.post(
        LOGIN_URL, json={"username": "analyst", "password": "spark-2026"}
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_register_rejects_duplicates_and_reserved(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": "analyst", "password": "spark-2026"},
    )
    assert resp.status_code == 200
    dup = await client.post(
        "/api/v1/auth/register",
        json={"username": "analyst", "password": "different-123"},
    )
    assert dup.status_code == 409

    reserved = await client.post(
        "/api/v1/auth/register",
        json={"username": settings.APP_USERNAME, "password": "whatever123"},
    )
    assert reserved.status_code == 409


@pytest.mark.asyncio
async def test_register_validation(client):
    short = await client.post(
        "/api/v1/auth/register",
        json={"username": "analyst", "password": "short"},
    )
    assert short.status_code == 422
    bad_chars = await client.post(
        "/api/v1/auth/register",
        json={"username": "bad name!", "password": "spark-2026"},
    )
    assert bad_chars.status_code == 422


@pytest.mark.asyncio
async def test_registered_user_wrong_password(client):
    await client.post(
        "/api/v1/auth/register",
        json={"username": "analyst", "password": "spark-2026"},
    )
    resp = await client.post(
        LOGIN_URL, json={"username": "analyst", "password": "wrong-pass"}
    )
    assert resp.status_code == 401
    ghost = await client.post(
        LOGIN_URL, json={"username": "ghost", "password": "spark-2026"}
    )
    assert ghost.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_tokens(client):
    body = await _login(client)
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    out = await client.post(LOGOUT_URL, headers=headers)
    assert out.status_code == 200

    me = await client.get(ME_URL, headers=headers)
    assert me.status_code == 403

    refresh = await client.post(
        REFRESH_URL, json={"refresh_token": body["refresh_token"]}
    )
    assert refresh.status_code == 403
