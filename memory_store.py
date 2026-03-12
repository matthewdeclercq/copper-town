"""SQLite-backed memory store replacing file-based memory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiosqlite


def parse_bullet_entries(text: str) -> list[str]:
    """Extract entries from bullet-list text. Handles '- ' prefixed and bare lines."""
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            entries.append(line[2:].strip())
        elif line:
            entries.append(line)
    return entries


@dataclass
class MemoryEntry:
    """A single memory row."""

    id: int
    agent_slug: str
    scope: str
    content: str
    created_at: str
    session_id: str | None
    active: bool
    pinned: bool = False


class MemoryStore:
    """Async SQLite memory store with WAL mode for concurrent reads."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create tables, set WAL mode."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_slug TEXT NOT NULL,
                scope TEXT NOT NULL CHECK(scope IN ('agent', 'global')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                session_id TEXT,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_agent_scope
            ON memories(agent_slug, scope, active)
        """)
        # Non-destructive migration: add pinned column if missing
        try:
            await self._db.execute(
                "ALTER TABLE memories ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
            )
            await self._db.commit()
        except Exception as e:
            if "duplicate column name" not in str(e):
                raise
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def add(
        self,
        agent_slug: str,
        content: str,
        scope: str = "agent",
        session_id: str | None = None,
        pin: bool = False,
    ) -> int | None:
        """Insert a memory entry, skipping exact duplicates. Returns row id or None if duplicate."""
        if self._db is None:
            raise RuntimeError("MemoryStore not initialized; call await initialize() first")
        # Dedup: skip if an identical active entry already exists
        cursor = await self._db.execute(
            "SELECT id FROM memories WHERE agent_slug=? AND scope=? AND content=? AND active=1 LIMIT 1",
            (agent_slug, scope, content),
        )
        if await cursor.fetchone():
            return None
        cursor = await self._db.execute(
            "INSERT INTO memories (agent_slug, scope, content, session_id, pinned) VALUES (?, ?, ?, ?, ?)",
            (agent_slug, scope, content, session_id, 1 if pin else 0),
        )
        await self._db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_memories(
        self, agent_slug: str, scope: str = "agent"
    ) -> list[MemoryEntry]:
        """Return all active memory entries for an agent+scope."""
        if self._db is None:
            raise RuntimeError("MemoryStore not initialized; call await initialize() first")
        cursor = await self._db.execute(
            "SELECT id, agent_slug, scope, content, created_at, session_id, active, pinned "
            "FROM memories WHERE agent_slug = ? AND scope = ? AND active = 1 ORDER BY id",
            (agent_slug, scope),
        )
        rows = await cursor.fetchall()
        return [
            MemoryEntry(
                id=row[0],
                agent_slug=row[1],
                scope=row[2],
                content=row[3],
                created_at=row[4],
                session_id=row[5],
                active=bool(row[6]),
                pinned=bool(row[7]),
            )
            for row in rows
        ]

    async def get_memory_text(self, agent_slug: str, scope: str = "agent") -> str:
        """Return memory as a bullet list string (for system prompt injection).

        Pinned entries appear first, wrapped in [Pinned]/[/Pinned] tags.
        """
        entries = await self.get_memories(agent_slug, scope)
        if not entries:
            return ""
        pinned = [e for e in entries if e.pinned]
        unpinned = [e for e in entries if not e.pinned]
        parts: list[str] = []
        if pinned:
            parts.append("[Pinned]")
            parts.extend(f"- {e.content}" for e in pinned)
            parts.append("[/Pinned]")
        parts.extend(f"- {e.content}" for e in unpinned)
        return "\n".join(parts)

    async def count_entries(self, agent_slug: str, scope: str = "agent") -> int:
        """Count active entries for an agent+scope."""
        if self._db is None:
            raise RuntimeError("MemoryStore not initialized; call await initialize() first")
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM memories WHERE agent_slug = ? AND scope = ? AND active = 1",
            (agent_slug, scope),
        )
        row = await cursor.fetchone()
        return row[0]  # type: ignore[index]

    async def replace_memories(
        self, agent_slug: str, scope: str, new_entries: list[str]
    ) -> None:
        """Soft-delete non-pinned entries and insert consolidated replacements.

        Pinned entries are preserved so compression cannot evict them.
        """
        if self._db is None:
            raise RuntimeError("MemoryStore not initialized; call await initialize() first")
        # Only soft-delete unpinned entries so pinned ones survive compression
        await self._db.execute(
            "UPDATE memories SET active = 0 "
            "WHERE agent_slug = ? AND scope = ? AND active = 1 AND pinned = 0",
            (agent_slug, scope),
        )
        await self._db.executemany(
            "INSERT INTO memories (agent_slug, scope, content) VALUES (?, ?, ?)",
            [(agent_slug, scope, content) for content in new_entries],
        )
        await self._db.commit()

    async def add_bulk(
        self,
        agent_slug: str,
        entries: list[str],
        scope: str = "agent",
        session_id: str | None = None,
    ) -> None:
        """Insert multiple memory entries, skipping exact duplicates."""
        for content in entries:
            await self.add(agent_slug, content, scope=scope, session_id=session_id)
