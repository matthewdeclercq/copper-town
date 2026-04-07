"""Session management for the HTTP API."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .config import MAX_CONCURRENT_SESSIONS, SESSION_TTL_SECONDS

if TYPE_CHECKING:
    from .engine import Engine


@dataclass
class Session:
    id: str
    agent_slug: str
    messages: list[dict]
    created_at: float
    last_accessed: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue, repr=False)


class SessionManager:
    """Manages chat sessions for the HTTP API."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def create(self, agent_slug: str, engine: Engine) -> Session:
        """Create a new session with system prompt initialized."""
        self._cleanup()

        agent = engine.agents.get(agent_slug)
        if not agent:
            raise ValueError(f"Agent '{agent_slug}' not found.")

        system_prompt = await engine._build_system_prompt(agent)
        now = time.time()
        session = Session(
            id=uuid.uuid4().hex[:12],
            agent_slug=agent_slug,
            messages=[{"role": "system", "content": system_prompt}],
            created_at=now,
            last_accessed=now,
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session:
            session.last_accessed = time.time()
        return session

    def delete(self, session_id: str) -> Session | None:
        return self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        return [
            {
                "id": s.id,
                "agent": s.agent_slug,
                "messages": sum(1 for m in s.messages if m["role"] in ("user", "assistant")),
                "created_at": s.created_at,
                "last_accessed": s.last_accessed,
            }
            for s in self._sessions.values()
        ]

    def _cleanup(self) -> None:
        """Evict expired sessions and enforce max concurrency via LRU."""
        if len(self._sessions) < MAX_CONCURRENT_SESSIONS:
            return  # fast path: no pressure

        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.last_accessed > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            del self._sessions[sid]

        while len(self._sessions) >= MAX_CONCURRENT_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda s: s.last_accessed)
            del self._sessions[oldest.id]
