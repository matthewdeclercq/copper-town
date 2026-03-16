"""Poll checker framework for trigger-driven automation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PollChecker(ABC):
    """Base class for poll-based trigger checkers.

    Subclasses implement `check()` to query an external condition and return
    a truthy string (the poll result) when the trigger should fire, or None
    to skip.
    """

    async def setup(self) -> None:
        """Called once when the scheduler starts. Override for init logic."""

    async def teardown(self) -> None:
        """Called once on scheduler shutdown. Override for cleanup."""

    @abstractmethod
    async def check(self, **kwargs: Any) -> str | None:
        """Return a result string if the trigger condition is met, else None."""


class NullChecker(PollChecker):
    """No-op checker for testing — always returns None."""

    async def check(self, **kwargs: Any) -> str | None:
        return None


# ── Registry ──────────────────────────────────────────────────────────────

_CHECKERS: dict[str, type[PollChecker]] = {
    "null": NullChecker,
}


def register_checker(name: str, cls: type[PollChecker]) -> None:
    """Register a poll checker class by name."""
    _CHECKERS[name] = cls


def get_checker(name: str) -> PollChecker:
    """Instantiate a registered poll checker by name. Raises KeyError if unknown."""
    cls = _CHECKERS[name]
    return cls()
