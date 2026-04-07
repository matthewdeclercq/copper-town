"""Session tracer: JSONL file writer + optional verbose stderr output."""
from __future__ import annotations

import json
import sys
import time
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .config import TRACES_DIR
from .events import Event, EventType
from .terminal import BOLD, CYAN, DIM, GREEN, MAG, RED, RESET, YELLOW

if TYPE_CHECKING:
    from .events import EventBus

_EventFormat = namedtuple("_EventFormat", ["color", "label", "template"])

_EVENT_FORMATS: dict[EventType, _EventFormat] = {
    EventType.AGENT_STARTED:      _EventFormat(BOLD + GREEN,  "AGENT START", 'task="{task55}"{depth_sfx}'),
    EventType.AGENT_COMPLETED:    _EventFormat(BOLD + GREEN,  "AGENT DONE ", "status={status}"),
    EventType.AGENT_FAILED:       _EventFormat(BOLD + RED,    "AGENT FAIL ", "error={error50}"),
    EventType.LLM_CALL_COMPLETE:  _EventFormat(BOLD + CYAN,   "LLM CALL   ",
        "model={model}  in={prompt_tokens}  out={completion_tokens}"
        "  tools={tool_calls_count}  {latency_ms:.0f}ms"),
    EventType.TOOL_CALL_COMPLETE: _EventFormat(BOLD + YELLOW, "TOOL CALL  ", "tool={tool}  {latency_ms:.0f}ms  {tool_status}"),
    EventType.TASK_DELEGATED:     _EventFormat(BOLD + MAG,    "DELEGATE   ", '→ {target}  task="{task45}"'),
    EventType.MEMORY_UPDATED:     _EventFormat(DIM,           "MEMORY     ", 'scope={scope}  "{content50}"'),
    EventType.TRIGGER_FIRED:      _EventFormat(BOLD + MAG,    "TRIG FIRE  ", 'name={name}  agent={agent}  type={trigger_type}'),
    EventType.TRIGGER_COMPLETED:  _EventFormat(BOLD + GREEN,  "TRIG DONE  ", 'name={name}  status={status}'),
    EventType.TRIGGER_ERROR:      _EventFormat(BOLD + RED,    "TRIG ERROR ", 'name={name}  error={error50}'),
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
    d["name"] = d.get("name", "?")
    d["agent"] = d.get("agent", "?")
    d["trigger_type"] = d.get("trigger_type", "?")
    d["depth_sfx"] = f"  depth={d['depth']}" if d.get("depth") else ""
    d["tool_status"] = "ok" if d.get("success") else f'ERR({d.get("error", "?")})'
    fmt = _EVENT_FORMATS.get(event.type)
    return fmt.template.format_map(d) if fmt else json.dumps(event.data)[:80]


def _verbose_line(event: Event, elapsed_s: float) -> str:
    fmt = _EVENT_FORMATS.get(event.type)
    color = fmt.color if fmt else ""
    label = fmt.label if fmt else event.type.value[:11].upper()
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


def format_trace(path: Path, records: list[dict]) -> None:
    """Pretty-print a trace file's contents to stdout."""
    HR = "─" * 70
    events = [r for r in records if r.get("record") == "event"]
    session_open = next((r for r in records if r.get("record") == "session_open"), None)
    session_close = next((r for r in records if r.get("record") == "session_close"), None)

    print(f"Trace: {path}")
    print(HR)
    print("\nTimeline")
    print(HR)

    agents: set[str] = set()
    counts = {"llm": 0, "tool": 0, "tool_fail": 0, "deleg": 0, "mem": 0, "trig": 0, "in": 0, "out": 0}
    failures: list[str] = []

    for ev in events:
        etype = ev.get("type", "")
        source = ev.get("source", "?")
        elapsed = ev.get("elapsed_s", 0.0)
        data = ev.get("data", {})
        agents.add(source)

        depth = data.get("depth", 0) if etype == "agent_started" else 0
        prefix = f"{'  ' + '  ' * depth}+{elapsed:>5.1f}s  {source:<18} "

        if etype == "agent_started":
            depth_sfx = f"  depth={depth}" if depth else ""
            print(f"{prefix}STARTED  \"{(data.get('task') or '')[:55]}\"{depth_sfx}")
        elif etype == "agent_completed":
            print(f"{prefix}DONE     status={data.get('status', '?')}")
        elif etype == "agent_failed":
            err = (data.get("error") or data.get("status", "?"))[:50]
            print(f"{prefix}FAILED   error={err}")
            failures.append(f"  +{elapsed:>5.1f}s  AGENT FAILED  {source}  {err}")
        elif etype == "llm_call_complete":
            counts["llm"] += 1
            in_tok, out_tok = data.get("prompt_tokens", 0), data.get("completion_tokens", 0)
            counts["in"] += in_tok; counts["out"] += out_tok
            print(f"{prefix}LLM      model={data.get('model', '?')}  in={in_tok}  out={out_tok}"
                  f"  tools={data.get('tool_calls_count', 0)}  {data.get('latency_ms', 0):.0f}ms")
        elif etype == "tool_call_complete":
            counts["tool"] += 1
            ok = data.get("success", True)
            if not ok:
                counts["tool_fail"] += 1
                failures.append(f"  +{elapsed:>5.1f}s  TOOL FAILED   {source}/{data.get('tool', '?')}  {data.get('error', '?')}")
            status = "ok" if ok else f"ERR({data.get('error', '?')})"
            print(f"{prefix}TOOL     {data.get('tool', '?')}  {data.get('latency_ms', 0):.0f}ms  {status}")
        elif etype == "task_delegated":
            counts["deleg"] += 1
            print(f"{prefix}DELEGATE → {data.get('target', '?')}  \"{(data.get('task') or '')[:45]}\"")
        elif etype == "memory_updated":
            counts["mem"] += 1
            print(f"{prefix}MEMORY   scope={data.get('scope', '?')}  \"{(data.get('content') or '')[:50]}\"")
        elif etype == "trigger_fired":
            counts["trig"] += 1
            print(f"{prefix}TRIG FIRE  name={data.get('name', '?')}  agent={data.get('agent', '?')}  type={data.get('trigger_type', '?')}")
        elif etype == "trigger_completed":
            print(f"{prefix}TRIG DONE  name={data.get('name', '?')}  status={data.get('status', '?')}")
        elif etype == "trigger_error":
            err = (data.get("error") or "?")[:50]
            print(f"{prefix}TRIG ERROR name={data.get('name', '?')}  error={err}")
            failures.append(f"  +{elapsed:>5.1f}s  TRIG FAILED   {data.get('name', '?')}  {err}")

    print(f"\nSummary")
    print(HR)
    ts = session_open.get("ts", "?") if session_open else "?"
    dur = session_close.get("elapsed_s", 0.0) if session_close else (events[-1].get("elapsed_s", 0.0) if events else 0.0)
    print(f"  Session start : {ts}")
    print(f"  Duration      : {dur:.1f}s")
    print(f"  Agents active : {', '.join(sorted(agents)) or 'none'}")
    print(f"  LLM calls     : {counts['llm']}")
    print(f"  Tool calls    : {counts['tool']}  (failed: {counts['tool_fail']})")
    print(f"  Delegations   : {counts['deleg']}")
    print(f"  Memory ops    : {counts['mem']}")
    print(f"  Trigger fires : {counts['trig']}")
    print(f"  Tokens in/out : {counts['in']} / {counts['out']}")

    if failures:
        print(f"\nFailures")
        print(HR)
        for line in failures:
            print(line)
