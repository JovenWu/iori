"""TypeSafe JEV (System One) client.

JEV returns typed judgments (Choice / Score / Noul) instead of generated text,
so every classification in the app — routing, retrieval gates, memory rerank,
memory dedup decisions — goes through here.

Every call site must tolerate `jev_ask` returning None: a missing API key or a
request failure falls back to the site's LLM/deterministic path, so a JEV
outage can never break a user-facing turn.
"""

import logging
from typing import Any, Mapping

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Noul,
    RetryPolicy,
    Score,
    SystemOneResponse,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

__all__ = ["Choice", "Noul", "Score", "jev_ask", "jev_close", "jev_enabled"]

_client: AsyncTypeSafeClient | None = None


def jev_enabled() -> bool:
    return bool(settings.TYPESAFE_API_KEY)


def _get_client() -> AsyncTypeSafeClient | None:
    global _client
    if not jev_enabled():
        return None
    if _client is None:
        _client = AsyncTypeSafeClient(
            api_key=settings.TYPESAFE_API_KEY,
            model=settings.TYPESAFE_MODEL,
            timeout=10.0,
            retry=RetryPolicy(max_retries=2, timeout=10.0),
        )
    return _client


async def jev_ask(
    state: Any,
    questions: Mapping[str, Noul | Choice | Score],
) -> SystemOneResponse | None:
    """Ask JEV questions about `state`. Returns None when JEV is unconfigured
    or the request fails — callers handle the fallback."""
    client = _get_client()
    if client is None:
        return None
    try:
        return await client.system_one(state, questions)
    except Exception:
        logger.warning("jev_ask: request failed", exc_info=True)
        return None


async def jev_close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
