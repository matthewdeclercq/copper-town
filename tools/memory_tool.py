"""Memory tool — schema only; the engine intercepts execution."""

from __future__ import annotations

from tools import tool


@tool
def remember(content: str, scope: str = "agent") -> str:
    """Save a fact or observation to persistent memory for future sessions.

    - content: The information to remember.
    - scope: "agent" to save to the current agent's memory, or "global" for shared memory.
    """
    # This function body is never called directly — the engine intercepts it.
    return ""
