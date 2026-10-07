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
    # run_turn launches _ensure_title concurrently — stub the LLM seam so no
    # real call happens; "" means "no title generated", fallback persists.
    monkeypatch.setattr(service, "_generate_title", AsyncMock(return_value=""))
    # Fresh AIMessage per call — reusing one object would share its `id`, and
    # add_messages treats a repeated id as an update rather than an append.
    async def _fake_ainvoke(messages, config=None):
        return AIMessage(content="Halo! Ada yang bisa dibantu?")

    fake = SimpleNamespace(ainvoke=_fake_ainvoke)
    # Both seams: `general` routes use the tool-less runnable, everything else
    # falls back to agent_llm.
    monkeypatch.setattr(nodes, "agent_llm", fake)
    monkeypatch.setitem(nodes._LLM_BY_WORKFLOW, "general", fake)


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
    assert threads.json()["total"] == 1  # full count rides along for "N of M"

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
async def test_thread_detail_reports_active_run(
    client, agent_service, fake_llm, monkeypatch
):
    """The detail flags a live run so a remounting client knows to reattach."""
    # Stall the LLM just long enough to read the detail mid-flight.
    async def slow_llm(messages, config=None):
        await asyncio.sleep(0.6)
        return AIMessage(content="lambat")

    slow = SimpleNamespace(ainvoke=slow_llm)
    monkeypatch.setattr(nodes, "agent_llm", slow)
    monkeypatch.setitem(nodes._LLM_BY_WORKFLOW, "general", slow)

    headers = await _login(client)
    req = client.build_request(
        "POST", STREAM_URL, json={"message": "halo"}, headers=headers
    )
    send = asyncio.create_task(client.send(req, stream=True))
    await asyncio.sleep(0.3)  # let the endpoint register the run

    threads = (await client.get("/api/v1/threads", headers=headers)).json()
    thread_id = threads["threads"][0]["id"]

    detail = (
        await client.get(f"/api/v1/threads/{thread_id}", headers=headers)
    ).json()
    assert detail["has_active_run"] is True

    resp = await send
    try:
        events = await _collect(resp)
    finally:
        await resp.aclose()
    assert events[-1]["type"] == "done"

    detail = (
        await client.get(f"/api/v1/threads/{thread_id}", headers=headers)
    ).json()
    assert detail["has_active_run"] is False


@pytest.mark.asyncio
async def test_stop_signals_run(client, agent_service, monkeypatch):
    async def no_jev(state, questions):
        return None

    monkeypatch.setattr(context, "jev_ask", no_jev)
    monkeypatch.setattr(context, "recall_memories", AsyncMock(return_value=""))
    monkeypatch.setattr(service, "_post_turn", AsyncMock())
    monkeypatch.setattr(service, "_generate_title", AsyncMock(return_value=""))

    async def slow_llm(messages, config=None):
        await asyncio.sleep(60)
        return AIMessage(content="never")

    slow = SimpleNamespace(ainvoke=slow_llm)
    monkeypatch.setattr(nodes, "agent_llm", slow)
    monkeypatch.setitem(nodes._LLM_BY_WORKFLOW, "general", slow)

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

    two_step = SimpleNamespace(ainvoke=two_step_llm)
    monkeypatch.setattr(nodes, "agent_llm", two_step)
    monkeypatch.setitem(nodes._LLM_BY_WORKFLOW, "general", two_step)

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
async def test_block_content_history_includes_reasoning(
    client, agent_service, fake_llm, monkeypatch
):
    """Reasoning models answer with typed content blocks — history must
    serialize the text blocks as `content` and summaries as `reasoning`."""
    block_reply = AIMessage(
        content=[
            {
                "type": "reasoning",
                "id": "rs_x",
                "summary": [
                    {"type": "summary_text", "text": "User greeted me — "},
                    {"type": "summary_text", "text": "respond warmly."},
                ],
            },
            {"type": "text", "text": "Halo! Senang bertemu."},
        ]
    )

    async def block_llm(messages, config=None):
        return block_reply

    fake = SimpleNamespace(ainvoke=block_llm)
    monkeypatch.setattr(nodes, "agent_llm", fake)
    monkeypatch.setitem(nodes._LLM_BY_WORKFLOW, "general", fake)

    headers = await _login(client)
    async with client.stream(
        "POST", STREAM_URL, json={"message": "halo"}, headers=headers
    ) as resp:
        events = await _collect(resp)
    assert events[-1]["type"] == "done"
    assert events[-1]["data"]["answer"] == "Halo! Senang bertemu."
    thread_id = events[-1]["data"]["thread_id"]

    detail = await client.get(f"/api/v1/threads/{thread_id}", headers=headers)
    msgs = detail.json()["messages"]
    assistant = next(m for m in msgs if m["role"] == "assistant")
    assert assistant["content"] == "Halo! Senang bertemu."
    assert assistant["reasoning"] == "User greeted me — respond warmly."


@pytest.mark.asyncio
async def test_thread_title_falls_back_to_first_message(
    client, agent_service, fake_llm
):
    headers = await _login(client)

    async with client.stream(
        "POST", STREAM_URL, json={"message": "halo"}, headers=headers
    ) as resp:
        events = await _collect(resp)
    thread_id = events[-1]["data"]["thread_id"]

    # _generate_title is stubbed to "" — the first-message fallback persists;
    # a refresh mid/post-run must never surface "Untitled".
    assert events[-1]["type"] == "done"
    detail = await client.get(f"/api/v1/threads/{thread_id}", headers=headers)
    assert detail.json()["title"] == "halo"


@pytest.mark.asyncio
async def test_llm_title_upgrades_placeholder(
    client, agent_service, fake_llm, monkeypatch
):
    """run_turn's concurrent _ensure_title commits the generated title."""
    monkeypatch.setattr(
        service, "_generate_title", AsyncMock(return_value="Sectors Deep Dive")
    )
    headers = await _login(client)

    async with client.stream(
        "POST", STREAM_URL, json={"message": "halo"}, headers=headers
    ) as resp:
        events = await _collect(resp)
    thread_id = events[-1]["data"]["thread_id"]

    # The title task is fire-and-forget — it usually commits mid-run, but
    # poll briefly so a slow loop iteration can't flake the assertion.
    title = ""
    for _ in range(40):
        detail = await client.get(f"/api/v1/threads/{thread_id}", headers=headers)
        title = detail.json()["title"]
        if title == "Sectors Deep Dive":
            break
        await asyncio.sleep(0.05)
    assert title == "Sectors Deep Dive"


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


@pytest.mark.asyncio
async def test_star_thread_keeps_updated_at(client, agent_service, fake_llm):
    headers = await _login(client)
    async with client.stream(
        "POST", STREAM_URL, json={"message": "halo"}, headers=headers
    ) as resp:
        events = await _collect(resp)
    thread_id = events[-1]["data"]["thread_id"]

    before = await client.get(f"/api/v1/threads/{thread_id}", headers=headers)
    assert before.json()["starred"] is False

    starred = await client.patch(
        f"/api/v1/threads/{thread_id}", json={"starred": True}, headers=headers
    )
    assert starred.status_code == 200
    assert starred.json()["starred"] is True
    # Starring is metadata, not activity — updated_at must not move.
    assert starred.json()["updated_at"] == before.json()["updated_at"]

    unstarred = await client.patch(
        f"/api/v1/threads/{thread_id}", json={"starred": False}, headers=headers
    )
    assert unstarred.json()["starred"] is False

    listed = await client.get("/api/v1/threads", headers=headers)
    row = next(t for t in listed.json()["threads"] if t["id"] == thread_id)
    assert "starred" in row


@pytest.mark.asyncio
async def test_list_returns_starred_beyond_loaded_pages(
    client, agent_service, fake_llm
):
    """A favorite buried in the recency order must still reach the client on
    page one — the sidebar/history pin it above the loaded window."""
    headers = await _login(client)
    ids = []
    for _ in range(3):
        async with client.stream(
            "POST", STREAM_URL, json={"message": "hi"}, headers=headers
        ) as resp:
            events = await _collect(resp)
        ids.append(events[-1]["data"]["thread_id"])
    oldest = ids[0]

    await client.patch(
        f"/api/v1/threads/{oldest}", json={"starred": True}, headers=headers
    )

    page = (await client.get("/api/v1/threads?limit=1", headers=headers)).json()
    assert [t["id"] for t in page["threads"]] == [ids[-1]]  # newest only
    assert [t["id"] for t in page["starred"]] == [oldest]
    assert page["total"] == 3

    # Deeper pages don't re-send the starred block — page one owns it.
    page2 = (
        await client.get(
            "/api/v1/threads",
            params={"limit": 1, "cursor": page["next_cursor"]},
            headers=headers,
        )
    ).json()
    assert page2["starred"] == []
