"""BackgroundTaskManager: unified state for background delegation tasks."""

from __future__ import annotations

import asyncio
from typing import Any, Callable


class BackgroundTaskManager:
    """Owns the five bg-task dicts that were previously scattered across Engine."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._meta: dict[str, dict[str, str]] = {}
        self._notifications: list[str] = []
        self._counter: dict[str, int] = {}
        self.on_notification: Callable[[str], None] | None = None

    # ── ID generation ──────────────────────────────────────────────

    def new_task_id(self, agent_slug: str) -> str:
        """Return a human-readable, incrementing task ID for *agent_slug*."""
        n = self._counter.get(agent_slug, 0) + 1
        self._counter[agent_slug] = n
        return f"{agent_slug}-{n}"

    # ── Task lifecycle ─────────────────────────────────────────────

    def register(
        self, task_id: str, agent_slug: str, task_desc: str, task: "asyncio.Task[Any]"
    ) -> None:
        self._tasks[task_id] = task
        self._meta[task_id] = {"agent": agent_slug, "task": task_desc}

    def complete(self, task_id: str) -> None:
        """Remove a finished task's records (called from task callback)."""
        self._tasks.pop(task_id, None)
        self._meta.pop(task_id, None)

    def cancel(self, task_id: str) -> str:
        """Cancel *task_id*. Returns 'cancelled', 'already_completed', or 'not_found'."""
        bg_task = self._tasks.get(task_id)
        if bg_task is None:
            return "not_found"
        if bg_task.done():
            self.complete(task_id)
            return "already_completed"
        bg_task.cancel()
        self.complete(task_id)
        self._notifications = [n for n in self._notifications if task_id not in n]
        return "cancelled"

    def get_meta(self, task_id: str) -> dict[str, str]:
        return self._meta.get(task_id, {})

    # ── Notifications ──────────────────────────────────────────────

    def add_notification(self, text: str) -> None:
        self._notifications.append(text)
        if self.on_notification is not None:
            self.on_notification(text)

    def drain_notifications(self) -> list[str]:
        """Return and clear all pending notification strings."""
        notes = list(self._notifications)
        self._notifications.clear()
        return notes

    def drain_into_messages(self, messages: list[dict]) -> list[str] | None:
        """Drain notifications and inject as system messages. Returns raw list or None."""
        pending = self.drain_notifications()
        if not pending:
            return None
        if len(pending) == 1:
            messages.append({"role": "system", "content": pending[0]})
        else:
            bundled = "\n\n---\n\n".join(pending)
            messages.append({
                "role": "system",
                "content": f"[{len(pending)} background tasks completed]\n\n{bundled}",
            })
        return pending

    # ── Introspection ──────────────────────────────────────────────

    @property
    def has_tasks(self) -> bool:
        return bool(self._tasks)

    def active_ids(self) -> list[str]:
        return list(self._tasks.keys())

    def active_meta(self) -> dict[str, dict[str, str]]:
        return dict(self._meta)

    def all_tasks(self) -> list["asyncio.Task[Any]"]:
        return list(self._tasks.values())

