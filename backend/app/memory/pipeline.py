"""Post-turn memory write path (Mem0-style).

For each extracted fact:
  1. Exact-hash dedup — byte-identical facts skip the whole pipeline.
  2. Retrieve top-k semantically similar existing memories.
  3. Decide the operation — JEV primary (one parallel Choice per candidate:
     restates / refines / contradicts / unrelated), LLM structured output as
     fallback.
  4. Apply: ADD / NOOP / DELETE+ADD / UPDATE (UPDATE merges old+new via one
     small LLM call — JEV cannot generate text).

Designed to run as a fire-and-forget background task: never raises.
"""

import logging
import uuid
from typing import Literal, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.jev import Choice, jev_ask
from app.core.llm import get_chat_model
from app.memory import store
from app.memory.extractor import extract_facts
from app.models.memory import Memory

logger = logging.getLogger(__name__)

_RELATION_CRITERIA = {
    "restates": "The new fact says essentially the same thing as this memory.",
    "refines": "The new fact updates or adds detail to this memory.",
    "contradicts": "The new fact conflicts with or invalidates this memory.",
    "unrelated": "The new fact is about a different aspect of the user.",
}

_FACT_PREFIX = "User"


class MemoryOperation(BaseModel):
    """LLM fallback decision when JEV is unavailable."""

    action: Literal["ADD", "UPDATE", "DELETE", "NOOP"]
    memory_id: str | None = Field(
        default=None, description="UUID of the target memory for UPDATE/DELETE"
    )
    updated_content: str | None = Field(
        default=None, description="Merged content for UPDATE"
    )


class MergedFact(BaseModel):
    merged: str = Field(
        description="Single self-contained fact merging old memory and new fact"
    )


_llm = get_chat_model(
    settings.CLASSIFIER_MODEL,
    temperature=0,
    timeout=30,
    max_retries=2,
)
_operation_llm = _llm.with_structured_output(MemoryOperation)
_merge_llm = _llm.with_structured_output(MergedFact)


async def _decide_with_jev(
    fact: str, similar: list[Memory]
) -> tuple[str, Memory | None] | None:
    """One JEV call: a parallel Choice question per candidate memory.

    Returns (action, target) — action in {ADD, NOOP, UPDATE, DELETE} — or None
    when JEV is unavailable and the caller should use the LLM path.
    """
    if not similar:
        return ("ADD", None)

    questions = {
        f"mem_{i}": Choice(
            instructions="How does the NEW fact relate to this existing memory?",
            criteria=dict(_RELATION_CRITERIA),
        )
        for i in range(len(similar))
    }
    state = {
        "new_fact": fact,
        "existing_memories": [
            {"index": i, "memory": m.content} for i, m in enumerate(similar)
        ],
    }
    result = await jev_ask(state, questions)
    if result is None:
        return None

    best_idx: int | None = None
    best_relation = ""
    best_confidence = -1.0
    for i in range(len(similar)):
        answer = result.choices.get(f"mem_{i}")
        if answer is None or answer.choice == "unrelated":
            continue
        if answer.confidence > best_confidence:
            best_idx, best_relation, best_confidence = (
                i,
                answer.choice,
                answer.confidence,
            )

    if best_idx is None:
        return ("ADD", None)

    target = similar[best_idx]
    action = {"restates": "NOOP", "refines": "UPDATE", "contradicts": "DELETE"}[
        best_relation
    ]
    return (action, target)


_UPDATE_SYSTEM = """You are a memory store manager for an AI assistant.

Decide how to integrate a new fact into the existing memory store. Choose exactly ONE operation:
- ADD    → genuinely new information not captured by any existing memory.
- UPDATE → refines an existing memory; give memory_id and updated_content merging both.
- DELETE → contradicts/supersedes an existing memory; give its memory_id.
- NOOP   → already fully captured; do nothing."""

_UPDATE_TEMPLATE = """New fact to evaluate:
"{fact}"

Semantically similar existing memories (UUID | content):
{similar_list}

Return your decision as JSON."""


async def _decide_with_llm(fact: str, similar: list[Memory]) -> MemoryOperation:
    if not similar:
        return MemoryOperation(action="ADD")
    similar_list = "\n".join(f"- {m.id} | {m.content}" for m in similar)
    try:
        return await _operation_llm.ainvoke(
            [
                SystemMessage(content=_UPDATE_SYSTEM),
                HumanMessage(
                    content=_UPDATE_TEMPLATE.format(
                        fact=fact, similar_list=similar_list
                    )
                ),
            ]
        )
    except Exception:
        logger.exception("_decide_with_llm: failed, defaulting to ADD")
        return MemoryOperation(action="ADD")


async def _merge_fact(existing: str, new_fact: str) -> str:
    """Merge an existing memory and its refinement into one statement."""
    prompt = (
        "Merge these two facts about a user into ONE short self-contained "
        "English statement starting with 'User'. Keep all durable "
        "information from both.\n\n"
        f"Existing: {existing}\nNew: {new_fact}"
    )
    try:
        result: MergedFact = await _merge_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )
        merged = result.merged.strip()
        return merged if merged.startswith(_FACT_PREFIX + " ") else new_fact
    except Exception:
        logger.exception("_merge_fact: failed, using new fact")
        return new_fact


async def _apply_decision(
    db: AsyncSession,
    user_id: int,
    thread_id: str | None,
    fact: str,
    action: str,
    target: Memory | None,
) -> None:
    if action == "NOOP":
        return
    if action == "DELETE" and target is not None:
        await store.delete_memory(db, target.id, user_id)
        await store.add_memory(db, user_id, fact, source_thread_id=thread_id)
        return
    if action == "UPDATE" and target is not None:
        merged = await _merge_fact(target.content, fact)
        updated = await store.update_memory(db, target.id, merged, user_id)
        if updated is None:
            await store.add_memory(db, user_id, fact, source_thread_id=thread_id)
        return
    await store.add_memory(db, user_id, fact, source_thread_id=thread_id)


async def _apply_llm_decision(
    db: AsyncSession,
    user_id: int,
    thread_id: str | None,
    fact: str,
    similar: list[Memory],
) -> None:
    op = await _decide_with_llm(fact, similar)

    if op.action == "NOOP" or op.action == "ADD":
        if op.action == "ADD":
            await store.add_memory(db, user_id, fact, source_thread_id=thread_id)
        return

    try:
        target_id = uuid.UUID(str(op.memory_id)) if op.memory_id else None
    except ValueError:
        target_id = None
    target = next((m for m in similar if m.id == target_id), None)
    if target is None:
        await store.add_memory(db, user_id, fact, source_thread_id=thread_id)
        return

    if op.action == "DELETE":
        await store.delete_memory(db, target.id, user_id)
        await store.add_memory(db, user_id, fact, source_thread_id=thread_id)
    else:  # UPDATE
        content = op.updated_content or fact
        if not content.startswith(_FACT_PREFIX + " "):
            content = fact
        updated = await store.update_memory(db, target.id, content, user_id)
        if updated is None:
            await store.add_memory(db, user_id, fact, source_thread_id=thread_id)


async def process_turn(
    user_id: int,
    thread_id: str | None,
    user_msg: str,
    assistant_msg: str,
    summary: str,
    recent_messages: Sequence[BaseMessage],
    db: AsyncSession,
) -> None:
    """Extract → dedup → decide → apply → cap. Never raises to the caller."""
    try:
        facts = await extract_facts(
            user_msg=user_msg,
            assistant_msg=assistant_msg,
            summary=summary,
            recent_messages=recent_messages,
        )
        if not facts:
            return

        for fact in facts:
            if await store.find_by_hash(
                db, user_id, Memory.compute_hash(fact)
            ):
                continue

            similar = await store.vector_search(db, user_id, fact, top_k=10)
            similar_memories = [m for m, _ in similar]

            decision = await _decide_with_jev(fact, similar_memories)
            if decision is not None:
                action, target = decision
                await _apply_decision(db, user_id, thread_id, fact, action, target)
            else:
                await _apply_llm_decision(db, user_id, thread_id, fact, similar_memories)

        await store.enforce_cap(db, user_id, settings.MEMORY_MAX_PER_USER)
        await db.commit()
    except Exception:
        logger.exception("process_turn: pipeline failed for user %d", user_id)
        await db.rollback()
