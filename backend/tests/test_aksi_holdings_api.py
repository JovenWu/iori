"""Holdings CRUD — the scope of a user's corporate-action checks."""

import pytest

from app.core.config import settings

URL = "/api/v1/aksi/holdings"


async def _login(client) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.APP_USERNAME, "password": settings.APP_PASSWORD},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_put_then_get_normalizes_and_sorts(client):
    h = await _login(client)
    resp = await client.put(URL, headers=h, json={"holdings": [
        {"symbol": "wifi.jk", "shares": 1000},
        {"symbol": "BBCA", "shares": 500, "avg_price": 8750},
    ]})
    assert resp.status_code == 200
    got = (await client.get(URL, headers=h)).json()["holdings"]
    assert got == [
        {"symbol": "BBCA", "shares": 500, "avg_price": 8750.0},
        {"symbol": "WIFI", "shares": 1000, "avg_price": None},
    ]


@pytest.mark.asyncio
async def test_put_replaces_previous_holdings(client):
    h = await _login(client)
    await client.put(URL, headers=h, json={"holdings": [
        {"symbol": "BBCA", "shares": 1}, {"symbol": "TLKM", "shares": 2}]})
    await client.put(URL, headers=h, json={"holdings": [{"symbol": "ASII", "shares": 3}]})
    got = (await client.get(URL, headers=h)).json()["holdings"]
    assert [x["symbol"] for x in got] == ["ASII"]


@pytest.mark.asyncio
async def test_invalid_payloads_rejected(client):
    h = await _login(client)
    bad_symbol = await client.put(URL, headers=h, json={"holdings": [{"symbol": "TOOLONG", "shares": 1}]})
    duplicate = await client.put(URL, headers=h, json={"holdings": [
        {"symbol": "BBCA", "shares": 1}, {"symbol": "bbca", "shares": 2}]})
    zero = await client.put(URL, headers=h, json={"holdings": [{"symbol": "BBCA", "shares": 0}]})
    assert [bad_symbol.status_code, duplicate.status_code, zero.status_code] == [422, 422, 422]


@pytest.mark.asyncio
async def test_requires_auth(client):
    assert (await client.get(URL)).status_code == 401
