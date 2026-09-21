"""Graph state.

`messages` is the full, never-trimmed history (add_messages appends).
`summarized_upto` is an index into it — everything before that index is
already folded into `summary`, so the agent only ever reads the tail.
Retrieved context lives in dedicated fields and is composed into the system
prompt per turn instead of being persisted as chat history.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    summary: str
    summarized_upto: int
    # Router output — which registered workflow owns this turn.
    workflow: str
    # Read-only context blocks composed into the system prompt per turn.
    recalled_memories: str
    related_threads: str
