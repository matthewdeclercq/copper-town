"""In-process async event bus for reactive inter-agent coordination."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger("copper_town.events")

EventCallback = Callable[["Event"], Coroutine[Any, Any, None]]


class EventType(str, Enum):
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    MEMORY_UPDATED = "memory_updated"
    TASK_DELEGATED = "task_delegated"
    TASK_SUBMITTED = "task_submitted"
    TASK_CANCELLED = "task_cancelled"
    LLM_CALL_COMPLETE = "llm_call_complete"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    TASK_BACKGROUND_STARTED = "task_background_started"
    CUSTOM = "custom"


@dataclass
class Event:
    type: EventType
    source: str  # agent_slug or "engine" or "manager"
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class EventBus:
    """Async pub/sub event bus with history."""

    def __init__(self, history_limit: int = 1000) -> None:
        self._subscribers: dict[EventType, list[EventCallback]] = {}
        self._global_subscribers: list[EventCallback] = []
        self._history: deque[Event] = deque(maxlen=history_limit)

    def subscribe(self, event_type: EventType, callback: EventCallback) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def subscribe_all(self, callback: EventCallback) -> None:
        self._global_subscribers.append(callback)

    def unsubscribe(self, event_type: EventType, callback: EventCallback) -> None:
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb is not callback
            ]

    def unsubscribe_all(self, callback: EventCallback) -> None:
        self._global_subscribers = [
            cb for cb in self._global_subscribers if cb is not callback
        ]

    async def publish(self, event: Event) -> None:
        """Fire all matching callbacks concurrently. Failed callbacks log warnings."""
        self._history.append(event)
        callbacks = list(self._global_subscribers)
        if event.type in self._subscribers:
            callbacks.extend(self._subscribers[event.type])
        if callbacks:
            results = await asyncio.gather(
                *(cb(event) for cb in callbacks),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.warning(
                        "Event callback failed for %s: %s", event.type, result
                    )

    def recent_events(
        self, event_type: EventType | None = None, limit: int = 20
    ) -> list[Event]:
        if event_type is None:
            return list(self._history)[-limit:]
        return [e for e in self._history if e.type == event_type][-limit:]
