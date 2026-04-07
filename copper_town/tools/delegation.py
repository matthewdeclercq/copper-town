"""Delegation tools — schema only; the engine intercepts execution."""

from __future__ import annotations

from . import tool


@tool(schema_only=True)
def delegate_to_agent(agent: str, task: str, context: str = "") -> str:
    """Delegate a task to another agent. The engine will route this to the target agent.

    - agent: The agent name to delegate to (e.g. "accounting").
    - task: A clear description of the task for the target agent.
    - context: Optional background from the current conversation to pass along.
    """
    ...


@tool(schema_only=True)
def delegate_background(agent: str, task: str, context: str = "") -> str:
    """Delegate a task to a sub-agent in the background (non-blocking). Returns immediately
    with a task_id. The result is delivered at the start of your next conversation turn.

    - agent: The agent slug to delegate to (same valid targets as delegate_to_agent).
    - task: A clear description of the task for the target agent.
    - context: Optional background from the current conversation to pass along.
    """
    ...


@tool(schema_only=True)
def cancel_background_task(task_id: str) -> str:
    """Cancel a running background task by its task_id.

    - task_id: The task_id returned by delegate_background (e.g. "google-workspace-1").
    """
    ...
