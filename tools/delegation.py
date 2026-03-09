"""Delegation tool — schema only; the engine intercepts execution."""

from __future__ import annotations

from tools import tool


@tool
def delegate_to_agent(agent: str, task: str, context: str = "") -> str:
    """Delegate a task to another agent. The engine will route this to the target agent.

    - agent: The agent name to delegate to (e.g. "accounting").
    - task: A clear description of the task for the target agent.
    - context: Optional background from the current conversation to pass along.
    """
    # This function body is never called directly — the engine intercepts it.
    return ""
