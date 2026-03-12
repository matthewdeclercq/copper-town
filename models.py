"""Structured inter-agent result types."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class AgentResult:
    """Typed result from an agent run, replacing free-form string returns."""

    status: AgentStatus
    result: str
    error: str | None = None
    agent_slug: str = ""
    task: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_tool_response(self) -> str:
        """JSON for LLM tool results (backward compat + status field)."""
        data: dict[str, Any] = {
            "status": self.status.value,
            "agent": self.agent_slug,
            "result": self.result,
        }
        if self.error:
            data["error"] = self.error
        return json.dumps(data)

    @property
    def succeeded(self) -> bool:
        return self.status == AgentStatus.SUCCESS
