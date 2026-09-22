"""Agent service: Postgres checkpointer, detached turn producer, thread CRUD.

The producer (`run_turn`) is a detached asyncio task — it survives the HTTP
connection that started it. Tokens stream into the run's replay buffer; on
stop, whatever accumulated is checkpointed so nothing is lost. After the turn
settles, a bounded background task extracts memories and refreshes the
thread digest.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Sequence

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_graph
from app.agent.runs import AgentRun, registry
from app.core.config import settings
from app.core.llm import get_chat_model
from app.db.session import async_session_maker
from app.memory.digests import maintain_digest
from app.memory.pipeline import process_turn
from app.models.thread import Thread

logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None
_saver: AsyncPostgresSaver | None = None
_graph = None
_memory_sem: asyncio.Semaphore | None = None


def _psycopg_dsn() -> str:
    return (
        f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )


async def init_service() -> None:
    """Open the checkpointer pool and compile the graph. Called from lifespan."""
    global _pool, _saver, _graph, _memory_sem
    _pool = AsyncConnectionPool(
        conninfo=_psycopg_dsn(),
        max_size=settings.CHECKPOINTER_POOL_MAX_SIZE,
        open=False,
        kwargs={"autocommit": True},
    )
    await _pool.open()
    _saver = AsyncPostgresSaver(_pool)
    await _saver.setup()
    _graph = build_graph().compile(checkpointer=_saver)
    _memory_sem = asyncio.Semaphore(settings.MEMORY_BACKGROUND_CONCURRENCY)
    logger.info("agent service ready (checkpointer pool <= %d)", settings.CHECKPOINTER_POOL_MAX_SIZE)


async def shutdown_service() -> None:
    global _pool, _saver, _graph, _memory_sem
    if _pool is not None:
        await _pool.close()
    _pool = _saver = _graph = _memory_sem = None


def get_graph():
    if _graph is None:
        raise RuntimeError("agent service not initialized")
    return _graph


def thread_lock(thread_id: str) -> asyncio.Lock:
    return registry.thread_lock(thread_id)


# ---------------------------------------------------------------------------
# Thread CRUD
# ---------------------------------------------------------------------------

THREAD_TITLE_FALLBACK_CHARS = 60


def _title_fallback(user_msg: str) -> str:
    """Placeholder title until the LLM names the thread — the first message."""
    return user_msg.strip()[:THREAD_TITLE_FALLBACK_CHARS] or "New thread"


def _title_is_placeholder(thread: Thread, seed_msg: str) -> bool:
    """True while the thread still shows the first-message fallback."""
    return not thread.title or thread.title == _title_fallback(seed_msg)


async def get_thread(
    db: AsyncSession, user_id: int, thread_id: str | uuid.UUID
) -> Thread | None:
    result = await db.execute(
        select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    )
    return result.scalars().first()


async def get_or_create_thread(
    db: AsyncSession,
    user_id: int,
    thread_id: str | uuid.UUID | None,
    message: str | None = None,
) -> Thread:
    if thread_id is not None:
        thread = await get_thread(db, user_id, thread_id)
        if thread is None:
            raise LookupError("Thread not found")
    else:
        thread = Thread(user_id=user_id)
        db.add(thread)
    # First-message placeholder — upgraded to the LLM title once the turn
    # settles. A refresh mid-run then shows the fallback, never "Untitled".
    if message is not None and not thread.title:
        thread.title = _title_fallback(message)
    await db.commit()
    await db.refresh(thread)
    return thread


async def list_threads(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 20,
    before: tuple[datetime, uuid.UUID] | None = None,
) -> tuple[list[Thread], str | None]:
    """Keyset-paginate on (updated_at, id): updated_at moves on every turn, so
    offset paging would skip/duplicate rows as the list shifts."""
    stmt = (
        select(Thread)
        .where(Thread.user_id == user_id)
        .order_by(Thread.updated_at.desc(), Thread.id.desc())
        .limit(limit + 1)  # one extra row to know whether a next page exists
    )
    if before is not None:
        stmt = stmt.where(tuple_(Thread.updated_at, Thread.id) < before)
    rows = list((await db.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    threads = rows[:limit]
    next_cursor = (
        f"{threads[-1].updated_at.isoformat()}_{threads[-1].id}"
        if has_more
        else None
    )
    return threads, next_cursor


async def update_thread(
    db: AsyncSession,
    user_id: int,
    thread_id: str | uuid.UUID,
    *,
    title: str | None = None,
    starred: bool | None = None,
) -> Thread | None:
    thread = await get_thread(db, user_id, thread_id)
    if thread is None:
        return None
    if title is not None:
        thread.title = title
    if starred is not None:
        # Star/unstar is metadata, not activity — pin updated_at so toggling
        # it doesn't reorder the recency-sorted thread list.
        await db.execute(
            update(Thread)
            .where(Thread.id == thread.id)
            .values(starred=starred, updated_at=thread.updated_at)
            .execution_options(synchronize_session=False)
        )
    await db.commit()
    await db.refresh(thread)
    return thread


async def delete_thread(
    db: AsyncSession, user_id: int, thread_id: str | uuid.UUID
) -> bool:
    thread = await get_thread(db, user_id, thread_id)
    if thread is None:
        return False
    await db.delete(thread)  # FK cascade removes its digest
    await db.commit()
    if _saver is not None:
        try:
            await _saver.adelete_thread(str(thread_id))
        except Exception:
            logger.exception("delete_thread: checkpoint purge failed for %s", thread_id)
    return True


async def get_thread_messages(thread_id: str | uuid.UUID) -> list[dict]:
    """Serialize the checkpointed message history for the API."""
    config = {"configurable": {"thread_id": str(thread_id)}}
    state = await get_graph().aget_state(config)
    values = state.values if state else {}
    out = []
    for m in values.get("messages", []):
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        else:
            continue
        if isinstance(m.content, str):
            out.append({"role": role, "content": m.content})
    return out


# ---------------------------------------------------------------------------
# Turn producer (detached)
# ---------------------------------------------------------------------------


def _chunk_text(msg: AIMessageChunk) -> str:
    """Plain text from a streamed chunk — string content or text blocks."""
    if isinstance(msg.content, str):
        return msg.content
    return "".join(
        b.get("text", "")
        for b in msg.content
        if isinstance(b, dict) and b.get("type") == "text"
    )


async def run_turn(
    run: AgentRun, user_id: int, thread_id: str, user_msg: str
) -> None:
    """Stream the graph for one turn into `run`'s buffer. Never raises."""
    # Title runs concurrently — independent of the answer and usually
    # committed before the stream closes.
    asyncio.create_task(_ensure_title(user_id, thread_id, user_msg))
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    accumulated = ""
    final_answer = ""
    try:
        async with async_session_maker() as db:
            config["configurable"]["db"] = db
            async for kind, payload in graph.astream(
                {"messages": [HumanMessage(content=user_msg)]},
                config,
                stream_mode=["messages", "updates"],
            ):
                if kind == "messages":
                    msg, meta = payload
                    if (
                        meta.get("langgraph_node") == "agent"
                        and isinstance(msg, AIMessageChunk)
                    ):
                        chunk = _chunk_text(msg)
                        if chunk:
                            accumulated += chunk
                            run.emit("token", chunk)
                elif kind == "updates":
                    for node_name, update in payload.items():
                        if not isinstance(update, dict):
                            continue
                        for m in update.get("messages", []):
                            if node_name == "agent" and isinstance(m, AIMessage):
                                if isinstance(m.content, str) and m.content:
                                    final_answer = m.content
                                for tc in m.tool_calls or []:
                                    run.emit(
                                        "tool",
                                        {"name": tc.get("name"), "status": "call"},
                                    )
                            elif node_name == "tools":
                                run.emit(
                                    "tool",
                                    {"name": getattr(m, "name", "tool"), "status": "done"},
                                )
        answer = accumulated or final_answer
        run.emit("done", {"answer": answer, "thread_id": thread_id})
    except asyncio.CancelledError:
        # Stop requested: checkpoint whatever partial answer accumulated.
        if accumulated:
            try:
                await graph.aupdate_state(
                    config, {"messages": [AIMessage(content=accumulated)]}
                )
            except Exception:
                logger.exception("run_turn: partial save failed")
        run.emit("stopped", {"answer": accumulated, "thread_id": thread_id})
    except Exception:
        logger.exception("run_turn failed for thread %s", thread_id)
        run.emit("error", "Generation failed.")
    finally:
        registry.finish(run)
        asyncio.create_task(_post_turn(user_id, thread_id))


# ---------------------------------------------------------------------------
# Post-turn housekeeping
# ---------------------------------------------------------------------------


async def _generate_title(user_msg: str) -> str:
    try:
        # Reasoning off — the title must be fast and just a few words.
        llm = get_chat_model(
            settings.CLASSIFIER_MODEL,
            temperature=0,
            timeout=20,
            reasoning_effort="none",
        )
        resp = await llm.ainvoke(
            "Write a 3-6 word conversation title (no quotes, no punctuation) "
            f"for a chat that starts with: {user_msg[:300]}"
        )
        return resp.content.strip()[: settings.THREAD_TITLE_MAX_CHARS]
    except Exception:
        logger.exception("_generate_title failed")
        return ""


async def _ensure_title(user_id: int, thread_id: str, user_msg: str) -> None:
    """Generate + persist the LLM title while the thread still shows the
    first-message placeholder. Runs concurrently with the turn so the title
    is usually committed before the run's stream closes; _post_turn retries
    on failure. Never raises."""
    try:
        async with async_session_maker() as db:
            thread = await get_thread(db, user_id, thread_id)
            if thread is None or not _title_is_placeholder(thread, user_msg):
                return
            generated = await _generate_title(user_msg)
            if not generated:
                return
            # The user may have renamed while the LLM was thinking.
            await db.refresh(thread)
            if not _title_is_placeholder(thread, user_msg):
                return
            thread.title = generated
            await db.commit()
    except Exception:
        logger.exception("_ensure_title failed for thread %s", thread_id)


async def _post_turn(user_id: int, thread_id: str) -> None:
    """Memory extraction + digest refresh + title. Best-effort, never raises."""
    assert _memory_sem is not None
    async with _memory_sem:
        try:
            config = {"configurable": {"thread_id": thread_id}}
            state = await get_graph().aget_state(config)
            values = state.values if state else {}
            messages: Sequence[BaseMessage] = values.get("messages", [])
            if len(messages) < 2:
                return
            user_msg = next(
                (m.content for m in reversed(messages) if isinstance(m, HumanMessage)),
                "",
            )
            ai_msg = next(
                (m.content for m in reversed(messages) if isinstance(m, AIMessage)),
                "",
            )
            if not isinstance(user_msg, str) or not isinstance(ai_msg, str):
                return
            summary = values.get("summary", "") or ""
            first_user_msg = next(
                (m.content for m in messages if isinstance(m, HumanMessage)),
                "",
            )

            async with async_session_maker() as db:
                thread = await get_thread(db, user_id, thread_id)
                # Title first — a fast invoke, user-facing. Commit it before
                # the slow memory work so clients refetching right after the
                # run see it. Keyed to the first user message so later turns
                # don't rename settled chats (a user rename survives too).
                if (
                    thread is not None
                    and isinstance(first_user_msg, str)
                    and _title_is_placeholder(thread, first_user_msg)
                ):
                    generated = await _generate_title(first_user_msg)
                    if generated:
                        thread.title = generated
                        await db.commit()
                title = thread.title if thread else None
                await process_turn(
                    user_id, thread_id, user_msg, ai_msg, summary, messages, db
                )
                await maintain_digest(
                    db, user_id, thread_id, title, summary, messages
                )
                if thread is not None and not thread.first_answer_preview:
                    thread.first_answer_preview = ai_msg[:200]
                await db.commit()
        except Exception:
            logger.exception("_post_turn failed for thread %s", thread_id)
