"""Session tracer: JSONL file writer + optional verbose stderr output."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .config import TRACES_DIR
from .events import Event, EventType
from .terminal import BOLD, CYAN, DIM, GREEN, MAG, RED, RESET, YELLOW

if TYPE_CHECKING:
    from .events import EventBus

_EVENT_COLORS = {
    EventType.AGENT_STARTED:      BOLD + GREEN,
    EventType.AGENT_COMPLETED:    BOLD + GREEN,
    EventType.AGENT_FAILED:       BOLD + RED,
    EventType.LLM_CALL_COMPLETE:  BOLD + CYAN,
    EventType.TOOL_CALL_COMPLETE: BOLD + YELLOW,
    EventType.TASK_DELEGATED:     BOLD + MAG,
    EventType.MEMORY_UPDATED:     DIM,
}
_EVENT_LABELS = {
    EventType.AGENT_STARTED:      "AGENT START",
    EventType.AGENT_COMPLETED:    "AGENT DONE ",
    EventType.AGENT_FAILED:       "AGENT FAIL ",
    EventType.LLM_CALL_COMPLETE:  "LLM CALL   ",
    EventType.TOOL_CALL_COMPLETE: "TOOL CALL  ",
    EventType.TASK_DELEGATED:     "DELEGATE   ",
    EventType.MEMORY_UPDATED:     "MEMORY     ",
}

# Templates are format_map()-d against a pre-processed copy of event.data.
# Each EventType entry here eliminates one branch from _format_detail.
# To add a new EventType: add a row here (and a color/label above).
_DETAIL_TEMPLATES: dict[EventType, str] = {
    EventType.AGENT_STARTED:      'task="{task55}"{depth_sfx}',
    EventType.AGENT_COMPLETED:    "status={status}",
    EventType.AGENT_FAILED:       "error={error50}",
    EventType.LLM_CALL_COMPLETE:  (
        "model={model}  in={prompt_tokens}  out={completion_tokens}"
        "  tools={tool_calls_count}  {latency_ms:.0f}ms"
    ),
    EventType.TOOL_CALL_COMPLETE: "tool={tool}  {latency_ms:.0f}ms  {tool_status}",
    EventType.TASK_DELEGATED:     '→ {target}  task="{task45}"',
    EventType.MEMORY_UPDATED:     'scope={scope}  "{content50}"',
}


def _format_detail(event: Event) -> str:
    d: dict = {
        "status": "?", "model": "?", "target": "?", "scope": "?", "tool": "?",
        "prompt_tokens": 0, "completion_tokens": 0, "tool_calls_count": 0, "latency_ms": 0.0,
        **event.data,
    }
    task = d.get("task") or ""
    d["task55"] = task[:55]
    d["task45"] = task[:45]
    d["error50"] = ((d.get("error") or d.get("status", "?"))[:50])
    d["content50"] = (d.get("content") or "")[:50]
    d["depth_sfx"] = f"  depth={d['depth']}" if d.get("depth") else ""
    d["tool_status"] = "ok" if d.get("success") else f'ERR({d.get("error", "?")})'
    tpl = _DETAIL_TEMPLATES.get(event.type)
    return tpl.format_map(d) if tpl else json.dumps(event.data)[:80]


def _verbose_line(event: Event, elapsed_s: float) -> str:
    color = _EVENT_COLORS.get(event.type, "")
    label = _EVENT_LABELS.get(event.type, event.type.value[:11].upper())
    return (
        f"{DIM}+{elapsed_s:>5.1f}s{RESET}  "
        f"{DIM}{CYAN}{event.source[:16]:<16}{RESET}  "
        f"{color}{label}{RESET}  {_format_detail(event)}"
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
