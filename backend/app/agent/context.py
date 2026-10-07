"""Context manager node: retrieval gates + rolling summarization.

One JEV call asks two parallel Noul questions — whether this turn needs
long-term user memory and whether it needs past-thread context — so a bare
"halo" never pays for an embedding + rerank pipeline. When JEV is
unavailable the fallback recalls memory (cheap, self-filtering) and skips
the thread signal (rarely needed).

Summarization folds everything before the last KEEP_TURNS human turns into
`summary` and advances `summarized_upto`; `messages` itself is never
trimmed, so checkpoint history stays complete.
"""

import logging
from pathlib import Path
from typing import Any, Sequence

import tiktoken
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agent.messages import message_reasoning, message_text, recent_context
from app.agent.state import ChatState
from app.core.config import settings
from app.core.jev import Noul, jev_ask
from app.core.llm import get_chat_model
from app.memory.digests import format_thread_signal, get_related_threads
from app.memory.recall import recall_memories

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "summarize.md"
_SUMMARIZE_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")

_encoding = tiktoken.get_encoding("cl100k_base")
_summarizer = get_chat_model(
    settings.CLASSIFIER_MODEL, temperature=0, timeout=30, max_retries=2
)

# Per-message framing overhead (role tokens etc.) on top of content tokens.
_MSG_OVERHEAD = 4


def count_tokens(text: str) -> int:
    return len(_encoding.encode(text))


def messages_tokens(messages: Sequence[BaseMessage]) -> int:
    total = 0
    for m in messages:
        # Reasoning blocks replay upstream with the message — their summary
        # approximates the token share (the encrypted blob itself is opaque).
        total += (
            count_tokens(message_text(m.content))
            + count_tokens(message_reasoning(m.content))
            + _MSG_OVERHEAD
        )
    return total


def _last_user_query(messages: Sequence[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            return m.content
    return ""


def _find_summary_boundary(
    messages: Sequence[BaseMessage], summarized_upto: int, keep_turns: int
) -> int | None:
    """Index of the human message that starts the KEEP_TURNS-th-from-last
    user turn, or None when there is nothing new to fold into the summary."""
    human_idx = [
        i for i, m in enumerate(messages) if isinstance(m, HumanMessage)
    ]
    if len(human_idx) <= keep_turns:
        return None
    boundary = human_idx[-keep_turns]
    return boundary if boundary > summarized_upto else None


async def _context_gates(query: str, summary: str, recent: str) -> tuple[bool, bool]:
    """JEV parallel Noul gates → (needs_user_memory, needs_past_chats).
    `recent` carries the last few turns so bare follow-ups still judge
    against their topic."""
    result = await jev_ask(
        {"latest_user_message": query, "recent_messages": recent,
         "conversation_summary": summary},
        {
            "needs_user_memory": Noul(
                instructions=(
                    "Does answering this message need stored facts about the "
                    "user — identity, preferences, portfolio, plans?"
                )
            ),
            "needs_past_chats": Noul(
                instructions=(
                    "Does this message reference or depend on earlier, "
                    "separate conversations with this user?"
                )
            ),
        },
    )
    if result is None:
        # Memory recall is cheap and self-filtering; the thread signal is
        # rarely needed, so fail open on memory and closed on threads.
        return True, False
    memory = result.nouls.get("needs_user_memory")
    threads = result.nouls.get("needs_past_chats")
    return (
        float(memory.noul) >= 0.5 if memory else True,
        float(threads.noul) >= 0.5 if threads else False,
    )


async def _summarize(existing: str, messages: Sequence[BaseMessage]) -> str:
    transcript = "\n".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {text}"
        for m in messages
        if isinstance(m, (HumanMessage, AIMessage))
        and (text := message_text(m.content))
    )
    if not transcript.strip():
        return existing
    try:
        resp = await _summarizer.ainvoke(
            _SUMMARIZE_TEMPLATE.format(summary=existing or "(none)", transcript=transcript)
        )
        return resp.content.strip() or existing
    except Exception:
        logger.exception("_summarize: failed, keeping previous summary")
        return existing


async def context_manager(state: ChatState, config: RunnableConfig) -> dict:
    cfg: dict[str, Any] = config.get("configurable", {})
    db = cfg.get("db")
    user_id = cfg.get("user_id")
    messages = state.get("messages", [])
    summary = state.get("summary", "")
    summarized_upto = state.get("summarized_upto", 0)

    updates: dict[str, Any] = {"recalled_memories": "", "related_threads": ""}
    query = _last_user_query(messages)
    recent = recent_context(messages)
    needs_memory, needs_threads = await _context_gates(query, summary, recent)

    if db is not None and user_id is not None and query:
        # The bare last message is often a follow-up ("what if I miss it?")
        # with no topic of its own — context lets retrieval find it.
        recall_q = f"{recent}\n{query}" if recent else query
        if needs_memory:
            try:
                updates["recalled_memories"] = await recall_memories(
                    db, user_id, recall_q
                )
            except Exception:
                logger.exception("context_manager: memory recall failed")
        if needs_threads:
            try:
                digests = await get_related_threads(
                    db, user_id, recall_q, exclude_thread_id=cfg.get("thread_id")
                )
                updates["related_threads"] = format_thread_signal(digests)
            except Exception:
                logger.exception("context_manager: thread recall failed")

    # Rolling summarization: fold everything before the last KEEP_TURNS
    # human turns into `summary` when the active window is over budget.
    active = messages[summarized_upto:]
    if messages_tokens(active) + count_tokens(summary) > settings.CONTEXT_TOKEN_LIMIT:
        boundary = _find_summary_boundary(
            messages, summarized_upto, settings.KEEP_TURNS
        )
        if boundary is not None:
            updates["summary"] = await _summarize(
                summary, messages[summarized_upto:boundary]
            )
            updates["summarized_upto"] = boundary

    return updates
