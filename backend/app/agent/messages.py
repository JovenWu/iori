"""Block-aware message content helpers.

Reasoning-capable models (OpenAI reasoning items via OpenRouter) return
content as typed blocks — {"type": "reasoning"|"text"|"function_call"|...} —
instead of a plain string. These read the pieces each consumer cares about:
`message_text` for the visible answer, `message_reasoning` for the model's
summary of its own thinking.
"""

from typing import Any


def message_text(content: Any) -> str:
    """Concatenated answer text — string content or `text` blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        b.get("text", "")
        for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    )


def message_reasoning(content: Any) -> str:
    """Concatenated reasoning-summary text from `reasoning` blocks."""
    if not isinstance(content, list):
        return ""
    return "".join(
        s.get("text", "")
        for b in content
        if isinstance(b, dict) and b.get("type") == "reasoning"
        for s in (b.get("summary") or [])
        if isinstance(s, dict)
    )
