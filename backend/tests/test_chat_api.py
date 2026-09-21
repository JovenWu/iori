"""End-to-end chat: SSE stream, checkpointed history, resume, stop, CRUD.

Runs the real graph + real Postgres checkpointer; only the LLM, JEV gates,
and post-turn hooks are mocked.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage

from app.agent import context, nodes, service
from app.core.config import settings
from app.models.user import User
from sqlalchemy import select

LOGIN_URL = "/api/v1/auth/login"
STREAM_URL = "/api/v1/chat/stream"


@pytest_asyncio.fixture
async def agent_service():
    await service.init_service()
    yield
    await service.shutdown_service()


@pytest.fixture
def fake_llm(monkeypatch):
    async def no_jev(state, questions):
        return None

    monkeypatch.setattr(context, "jev_ask", no_jev)
    monkeypatch.setattr(context, "recall_memories", AsyncMock(return_value=""))
    monkeypatch.setattr(service, "_post_turn", AsyncMock())
    # Fresh AIMessage per call — reusing one object would share its `id`, and
    # add_messages treats a repeated id as an update rather than an append.
    async def _fake_ainvoke(messages, config=None):
        return AIMessage(content="Halo! Ada yang bisa dibantu?")

    monkeypatch.setattr(
        nodes, "agent_llm", SimpleNamespace(ainvoke=_fake_ainvoke)
    )


async def _login(client) -> dict:
    resp = await client.post(
        LOGIN_URL,
        json={"username": settings.APP_USERNAME, "password": settings.APP_PASSWORD},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _collect(resp) -> list[dict]:
    events = []
    async for line in resp.aiter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.mark.asyncio
async def test_stream_turn_persists_history(client, agent_service, fake_llm):
    headers = await _login(client)

    async with client.stream(
        "POST", STREAM_URL, json={"message": "halo"}, headers=headers
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = await _collect(resp)

    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[-1]["type"] == "done"
    assert events[-1]["data"]["answer"] == "Halo! Ada yang bisa dibantu?"
    thread_id = events[-1]["data"]["thread_id"]

    # Thread list + checkpointed history
    threads = await client.get("/api/v1/threads", headers=headers)
    assert [t["id"] for t in threads.json()["threads"]] == [thread_id]

    detail = await client.get(f"/api/v1/threads/{thread_id}", headers=headers)
    assert [m["role"] for m in detail.json()["messages"]] == ["user", "assistant"]

    # Second turn appends to the same checkpoint.
    async with client.stream(
        "POST",
        STREAM_URL,
        json={"thread_id": thread_id, "message": "siapa saya"},
        headers=headers,
    ) as resp:
        events2 = await _collect(resp)
    assert events2[-1]["type"] == "done", f"turn 2 events: {events2}"
    detail = await client.get(f"/api/v1/threads/{thread_id}", headers=headers)
    assert len(detail.json()["messages"]) == 4


@pytest.mark.asyncio
async def test_resume_replays_finished_run(client, agent_service, fake_llm):
    headers = await _login(client)
    async with client.stream(
        "POST", STREAM_URL, json={"message": "halo"}, headers=headers
    ) as resp:
        events = await _collect(resp)
    thread_id = events[-1]["data"]["thread_id"]

    # Re-attach within the linger window → full replay then stream closes.
    async with client.stream(
        "GET", f"/api/v1/threads/{thread_id}/stream", headers=headers
    ) as resp:
        assert resp.status_code == 200
        replayed = await _collect(resp)
    assert [e["seq"] for e in replayed] == [e["seq"] for e in events]

    # Partial replay from a seq cursor.
    async with client.stream(
        "GET",
        f"/api/v1/threads/{thread_id}/stream?last_seq={events[0]['seq']}",
        headers=headers,
    ) as resp:
        partial = await _collect(resp)
    assert partial == events[1:]


@pytest.mark.asyncio
async def test_stop_signals_run(client, agent_service, monkeypatch):
    async def no_jev(state, questions):
        return None

    monkeypatch.setattr(context, "jev_ask", no_jev)
    monkeypatch.setattr(context, "recall_memories", AsyncMock(return_value=""))
    monkeypatch.setattr(service, "_post_turn", AsyncMock())

    async def slow_llm(messages, config=None):
        await asyncio.sleep(60)
        return AIMessage(content="never")

    monkeypatch.setattr(nodes, "agent_llm", SimpleNamespace(ainvoke=slow_llm))

    headers = await _login(client)

    # ASGITransport only hands back the response once the SSE body produces a
    # byte — with a stalled LLM that means "when the run ends". Dispatch the
    # request as a background task so we can stop the run mid-flight.
    req = client.build_request(
        "POST", STREAM_URL, json={"message": "hi"}, headers=headers
    )
    send = asyncio.create_task(client.send(req, stream=True))
    await asyncio.sleep(0.3)  # let the endpoint register the run

    threads = (await client.get("/api/v1/threads", headers=headers)).json()
    thread_id = threads["threads"][0]["id"]

    out = await client.post(f"/api/v1/threads/{thread_id}/stop", headers=headers)
    assert out.status_code == 200
    assert out.json()["stopped"] is True

    resp = await send
    try:
        events = await _collect(resp)
    finally:
        await resp.aclose()
    assert events[-1]["type"] == "stopped"


@pytest.mark.asyncio
async def test_stream_emits_tool_events(client, agent_service, fake_llm, monkeypatch):
    from app.sectors import client as sectors_client

    calls = []

    async def fake_get(path, params=None):
        calls.append(path)
        return 200, {"sectors": [{"banks": "Financials"}]}

    monkeypatch.setattr(sectors_client, "get", fake_get)

    responses = iter(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "sectors_list_subsectors",
                        "args": {},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="IDX subsectors: banks → Financials."),
        ]
    )

    async def two_step_llm(messages, config=None):
        return next(responses)

    monkeypatch.setattr(nodes, "agent_llm", SimpleNamespace(ainvoke=two_step_llm))

    headers = await _login(client)
    async with client.stream(
        "POST", STREAM_URL, json={"message": "subsectors?"}, headers=headers
    ) as resp:
        events = await _collect(resp)

    tool_events = [e for e in events if e["type"] == "tool"]
    assert [e["data"]["status"] for e in tool_events] == ["call", "done"]
    assert tool_events[0]["data"]["name"] == "sectors_list_subsectors"
    assert calls == ["/v2/subsectors/"]
    assert events[-1]["type"] == "done"
    assert "banks" in events[-1]["data"]["answer"]


@pytest.mark.asyncio
async def test_thread_ownership_and_delete(client, agent_service, fake_llm, db):
    headers = await _login(client)
    other = User(username="other")
    db.add(other)
    await db.commit()
    await db.refresh(other)

    async with client.stream(
        "POST", STREAM_URL, json={"message": "halo"}, headers=headers
    ) as resp:
        events = await _collect(resp)
    thread_id = events[-1]["data"]["thread_id"]

    # A different user's token cannot see the thread — mint one for `other`.
    from app.core.security import create_access_token

    token = create_access_token(other.id, other.token_version)
    other_headers = {"Authorization": f"Bearer {token}"}
    assert (
        await client.get(f"/api/v1/threads/{thread_id}", headers=other_headers)
    ).status_code == 404

    # Owner deletes; checkpoints + digest cascade.
    deleted = await client.delete(
        f"/api/v1/threads/{thread_id}", headers=headers
    )
    assert deleted.status_code == 200
    gone = await client.get(f"/api/v1/threads/{thread_id}", headers=headers)
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_rename_thread(client, agent_service, fake_llm):
    headers = await _login(client)
    async with client.stream(
        "POST", STREAM_URL, json={"message": "halo"}, headers=headers
    ) as resp:
        events = await _collect(resp)
    thread_id = events[-1]["data"]["thread_id"]

    renamed = await client.patch(
        f"/api/v1/threads/{thread_id}",
        json={"title": "BBCA deep dive"},
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "BBCA deep dive"

    detail = await client.get(f"/api/v1/threads/{thread_id}", headers=headers)
    assert detail.json()["title"] == "BBCA deep dive"

    # Validation + ownership
    assert (
        await client.patch(
            f"/api/v1/threads/{thread_id}", json={"title": ""}, headers=headers
        )
    ).status_code == 422
    assert (
        await client.patch(
            "/api/v1/threads/00000000-0000-0000-0000-000000000000",
            json={"title": "nope"},
            headers=headers,
        )
    ).status_code == 404
