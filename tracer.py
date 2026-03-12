"""Session tracer: JSONL file writer + optional verbose stderr output."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from config import TRACES_DIR
from events import Event, EventType

if TYPE_CHECKING:
    from events import EventBus

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[92m"
_CYAN = "\033[96m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_MAG = "\033[95m"

_EVENT_COLORS = {
    EventType.AGENT_STARTED: _BOLD + _GREEN,
    EventType.AGENT_COMPLETED: _BOLD + _GREEN,
    EventType.AGENT_FAILED: _BOLD + _RED,
    EventType.LLM_CALL_COMPLETE: _BOLD + _CYAN,
    EventType.TOOL_CALL_COMPLETE: _BOLD + _YELLOW,
    EventType.TASK_DELEGATED: _BOLD + _MAG,
    EventType.MEMORY_UPDATED: _DIM,
}
_EVENT_LABELS = {
    EventType.AGENT_STARTED: "AGENT START",
    EventType.AGENT_COMPLETED: "AGENT DONE ",
    EventType.AGENT_FAILED: "AGENT FAIL ",
    EventType.LLM_CALL_COMPLETE: "LLM CALL   ",
    EventType.TOOL_CALL_COMPLETE: "TOOL CALL  ",
    EventType.TASK_DELEGATED: "DELEGATE   ",
    EventType.MEMORY_UPDATED: "MEMORY     ",
}


def _format_detail(event: Event) -> str:
    d, t = event.data, event.type
    if t == EventType.AGENT_STARTED:
        depth = d.get("depth", 0)
        return f'task="{(d.get("task") or "")[:55]}"' + (f"  depth={depth}" if depth else "")
    if t == EventType.AGENT_COMPLETED:
        return f'status={d.get("status", "?")}'
    if t == EventType.AGENT_FAILED:
        return f'error={(d.get("error") or d.get("status", "?"))[:50]}'
    if t == EventType.LLM_CALL_COMPLETE:
        return (
            f'model={d.get("model", "?")}  in={d.get("prompt_tokens", 0)}  '
            f'out={d.get("completion_tokens", 0)}  tools={d.get("tool_calls_count", 0)}  '
            f'{d.get("latency_ms", 0):.0f}ms'
        )
    if t == EventType.TOOL_CALL_COMPLETE:
        status = "ok" if d.get("success") else f'ERR({d.get("error", "?")})'
        return f'tool={d.get("tool", "?")}  {d.get("latency_ms", 0):.0f}ms  {status}'
    if t == EventType.TASK_DELEGATED:
        return f'→ {d.get("target", "?")}  task="{(d.get("task") or "")[:45]}"'
    if t == EventType.MEMORY_UPDATED:
        return f'scope={d.get("scope", "?")}  "{(d.get("content") or "")[:50]}"'
    return json.dumps(d)[:80]


def _verbose_line(event: Event, elapsed_s: float) -> str:
    color = _EVENT_COLORS.get(event.type, "")
    label = _EVENT_LABELS.get(event.type, event.type.value[:11].upper())
    return (
        f"{_DIM}+{elapsed_s:>5.1f}s{_RESET}  "
        f"{_DIM}{_CYAN}{event.source[:16]:<16}{_RESET}  "
        f"{color}{label}{_RESET}  {_format_detail(event)}"
    )


class SessionTracer:
    def __init__(
        self,
        event_bus: "EventBus",
        agent_slug: str,
        *,
        verbose: bool = False,
        silent_trace: bool = False,
    ) -> None:
        self._verbose = verbose
        self._silent_trace = silent_trace
        self._t0 = time.monotonic()
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        self._path = TRACES_DIR / f"{ts}_{agent_slug}.jsonl"
        self._file = self._path.open("a", encoding="utf-8")
        event_bus.subscribe_all(self._handle_event)
        self._write(
            {
                "record": "session_open",
                "agent": agent_slug,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def _handle_event(self, event: Event) -> None:
        elapsed_s = time.monotonic() - self._t0
        self._write(
            {
                "record": "event",
                "type": event.type.value,
                "source": event.source,
                "elapsed_s": round(elapsed_s, 3),
                "ts": event.timestamp.isoformat(),
                "data": event.data,
            }
        )
        if self._verbose:
            print(_verbose_line(event, elapsed_s), file=sys.stderr, flush=True)

    def _write(self, record: dict) -> None:
        self._file.write(json.dumps(record, default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._write(
            {
                "record": "session_close",
                "elapsed_s": round(time.monotonic() - self._t0, 3),
            }
        )
        self._file.close()
        if self._verbose or self._silent_trace:
            print(f"\nTrace: {self._path}", file=sys.stderr)

    @property
    def path(self) -> Path:
        return self._path
