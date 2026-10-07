"""Check runs over SSE, persisted reports, and the no-LLM impact endpoint."""

import json

import pytest

from app.core.config import settings
from tests import aksi_fixtures as fx

pytestmark = pytest.mark.asyncio


async def _login(client) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.APP_USERNAME, "password": settings.APP_PASSWORD},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _collect(resp) -> list[dict]:
    return [json.loads(line[6:]) async for line in resp.aiter_lines() if line.startswith("data: ")]


async def _check(client, headers, body) -> list[dict]:
    async with client.stream("POST", "/api/v1/aksi/check", json=body, headers=headers) as resp:
        assert resp.status_code == 200
        return await _collect(resp)


async def test_check_streams_and_persists_report(client, monkeypatch):
    fx.install_fakes(monkeypatch)
    h = await _login(client)
    await client.put("/api/v1/aksi/holdings", headers=h, json={"holdings": [
        {"symbol": "WIFI", "shares": 1000}, {"symbol": "BBMD", "shares": 5000}]})

    events = await _check(client, h, {"as_of": fx.AS_OF})
    assert events[0]["type"] == "started" and events[0]["data"]["mode"] == "replay"
    assert events[-1]["type"] == "done" and events[-1]["data"]["events"] == 2
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))

    report = (await client.get("/api/v1/aksi/reports/latest", headers=h)).json()
    assert report["status"] == "done" and report["mode"] == "replay"
    assert len(report["events"]) == 2 and report["credits_spent"] == 9
    same = (await client.get(f"/api/v1/aksi/reports/{report['id']}", headers=h)).json()
    assert same["id"] == report["id"]


async def test_check_without_holdings_finishes_empty(client, monkeypatch):
    fx.install_fakes(monkeypatch)
    h = await _login(client)
    events = await _check(client, h, {"as_of": fx.AS_OF})
    assert [e["type"] for e in events] == ["started", "done"]
    assert events[-1]["data"]["events"] == 0


async def test_impact_returns_figures(client, monkeypatch):
    fx.install_fakes(monkeypatch)
    h = await _login(client)
    resp = await client.post("/api/v1/aksi/impact", headers=h,
                             json={"symbol": "wifi", "shares": 1000, "as_of": fx.AS_OF})
    body = resp.json()
    assert resp.status_code == 200 and body["symbol"] == "WIFI"
    assert body["events"][0]["figures"]["rights_entitled"]["value"] == 1250


async def test_latest_replay_report_filters_by_as_of(client, monkeypatch):
    fx.install_fakes(monkeypatch)
    h = await _login(client)
    await _check(client, h, {"as_of": fx.AS_OF})
    ok = await client.get(
        f"/api/v1/aksi/reports/latest?mode=replay&as_of={fx.AS_OF}", headers=h)
    assert ok.status_code == 200 and ok.json()["as_of"] == fx.AS_OF
    miss = await client.get(
        "/api/v1/aksi/reports/latest?mode=replay&as_of=2021-01-04", headers=h)
    assert miss.status_code == 404


async def test_latest_report_404_before_any_check(client):
    h = await _login(client)
    assert (await client.get("/api/v1/aksi/reports/latest", headers=h)).status_code == 404
