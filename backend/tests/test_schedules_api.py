"""Schedules REST — CRUD, validation, auth scoping, run-now."""

import asyncio

import pytest

from app.core.config import settings

URL = "/api/v1/schedules"


async def _login(client) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.APP_USERNAME,
              "password": settings.APP_PASSWORD},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_list_get(client):
    h = await _login(client)
    resp = await client.post(URL, headers=h, json={
        "name": "Nightly scan", "prompt": "check holdings", "frequency": "daily"})
    assert resp.status_code == 200, resp.text
    job = resp.json()
    assert job["run_time"] == "17:00:00" and job["enabled"] is True
    assert job["next_run_at"] is not None and job["thread_id"]
    # The backing thread is a real thread, flagged as scheduled so the UI
    # can mark it in lists.
    threads = (await client.get("/api/v1/threads", headers=h)).json()
    row = next(t for t in threads["threads"] if t["id"] == job["thread_id"])
    assert row["title"] == "Nightly scan"
    assert row["scheduled"] is True
    assert all(
        t["scheduled"] is (t["id"] == job["thread_id"]) for t in threads["threads"]
    )
    listed = (await client.get(URL, headers=h)).json()
    assert [j["id"] for j in listed] == [job["id"]]


@pytest.mark.asyncio
async def test_validation(client):
    h = await _login(client)
    no_weekday = await client.post(URL, headers=h, json={
        "name": "w", "prompt": "p", "frequency": "weekly"})
    no_dom = await client.post(URL, headers=h, json={
        "name": "m", "prompt": "p", "frequency": "monthly"})
    bad_freq = await client.post(URL, headers=h, json={
        "name": "x", "prompt": "p", "frequency": "hourly"})
    assert [no_weekday.status_code, no_dom.status_code,
            bad_freq.status_code] == [422, 422, 422]


@pytest.mark.asyncio
async def test_patch_and_delete_keeps_thread(client):
    h = await _login(client)
    job = (await client.post(URL, headers=h, json={
        "name": "a", "prompt": "p", "frequency": "daily"})).json()
    patched = await client.patch(f"{URL}/{job['id']}", headers=h, json={
        "name": "b", "enabled": False, "frequency": "weekly", "weekday": 1})
    assert patched.status_code == 200
    assert patched.json()["frequency"] == "weekly" and patched.json()["weekday"] == 1
    bad = await client.patch(f"{URL}/{job['id']}", headers=h,
                             json={"frequency": "monthly"})
    assert bad.status_code == 422
    tid = job["thread_id"]
    assert (await client.delete(f"{URL}/{job['id']}", headers=h)).status_code == 200
    assert (await client.get(URL, headers=h)).json() == []
    # Thread survives the job.
    threads = (await client.get("/api/v1/threads", headers=h)).json()
    assert any(t["id"] == tid for t in threads["threads"])


@pytest.mark.asyncio
async def test_run_now(client, bound_session_maker, monkeypatch):
    from app.agent import service
    from app.agent.runs import registry

    fired = []

    async def fake_run_turn(run, user_id, thread_id, user_msg, lang="en",
                            scheduled=False):
        fired.append((user_id, thread_id, user_msg, scheduled))
        run.emit("done", {"answer": "ok", "thread_id": thread_id})
        registry.finish(run)

    monkeypatch.setattr(service, "run_turn", fake_run_turn)

    h = await _login(client)
    job = (await client.post(URL, headers=h, json={
        "name": "fire", "prompt": "do it now", "frequency": "daily"})).json()
    resp = await client.post(f"{URL}/{job['id']}/run", headers=h)
    assert resp.status_code == 200 and resp.json()["status"] == "fired"
    # The producer task is detached — poll briefly for it to run.
    for _ in range(50):
        if fired:
            break
        await asyncio.sleep(0.02)
    assert fired and fired[0][2] == "do it now" and fired[0][3] is True
    assert fired[0][1] == job["thread_id"]
    again = await client.post(f"{URL}/{job['id']}/run", headers=h)
    assert again.json()["status"] in ("fired", "skipped", "busy")


@pytest.mark.asyncio
async def test_requires_auth(client):
    assert (await client.get(URL)).status_code == 401
    assert (await client.post(URL, json={})).status_code == 401
