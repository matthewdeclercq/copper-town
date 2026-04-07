"""In-process async event bus for reactive inter-agent coordination."""

from __future__ import annotations

import asyncio
import logging
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
    TRIGGER_FIRED = "trigger_fired"
    TRIGGER_COMPLETED = "trigger_completed"
    TRIGGER_ERROR = "trigger_error"
    CUSTOM = "custom"


@dataclass
class Event:
    type: EventType
    source: str  # agent_slug or "engine" or "manager"
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class EventBus:
    """Async pub/sub event bus."""

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[EventCallback]] = {}
        self._global_subscribers: list[EventCallback] = []

    def subscribe(self, event_type: EventType, callback: EventCallback) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)

    def subscribe_all(self, callback: EventCallback) -> None:
        self._global_subscribers.append(callback)

    def unsubscribe(self, event_type: EventType, callback: EventCallback) -> None:
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb is not callback
            ]

    async def publish(self, event: Event) -> None:
        """Fire all matching callbacks concurrently. Failed callbacks log warnings."""
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
