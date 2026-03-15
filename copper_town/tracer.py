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
    _HR = "─" * 70

    session_open = next((r for r in records if r.get("record") == "session_open"), None)
    session_close = next((r for r in records if r.get("record") == "session_close"), None)
    events = [r for r in records if r.get("record") == "event"]

    print(f"Trace: {path}")
    print(_HR)

    # Timeline
    print("\nTimeline")
    print(_HR)

    agents_active: set[str] = set()
    llm_calls = 0
    tool_calls = 0
    tool_failures = 0
    delegations = 0
    memory_ops = 0
    total_in = 0
    total_out = 0
    failures: list[dict] = []

    for ev in events:
        etype = ev.get("type", "")
        source = ev.get("source", "?")
        elapsed = ev.get("elapsed_s", 0.0)
        data = ev.get("data", {})

        agents_active.add(source)

        depth = data.get("depth", 0) if etype == "agent_started" else 0
        indent = "  " + ("  " * depth)

        if etype == "agent_started":
            task_preview = (data.get("task") or "")[:55]
            depth_str = f"  depth={depth}" if depth else ""
            print(f"{indent}+{elapsed:>5.1f}s  {source:<18} STARTED  \"{task_preview}\"{depth_str}")
        elif etype == "agent_completed":
            print(f"{indent}+{elapsed:>5.1f}s  {source:<18} DONE     status={data.get('status', '?')}")
        elif etype == "agent_failed":
            err = (data.get("error") or data.get("status", "?"))[:50]
            print(f"{indent}+{elapsed:>5.1f}s  {source:<18} FAILED   error={err}")
            failures.append({"type": "agent", "source": source, "error": err, "elapsed_s": elapsed})
        elif etype == "llm_call_complete":
            llm_calls += 1
            in_tok = data.get("prompt_tokens", 0)
            out_tok = data.get("completion_tokens", 0)
            total_in += in_tok
            total_out += out_tok
            latency = data.get("latency_ms", 0)
            model = data.get("model", "?")
            tools_count = data.get("tool_calls_count", 0)
            print(
                f"{indent}+{elapsed:>5.1f}s  {source:<18} LLM      "
                f"model={model}  in={in_tok}  out={out_tok}  tools={tools_count}  {latency:.0f}ms"
            )
        elif etype == "tool_call_complete":
            tool_calls += 1
            success = data.get("success", True)
            if not success:
                tool_failures += 1
            tool_name = data.get("tool", "?")
            latency = data.get("latency_ms", 0)
            status = "ok" if success else f"ERR({data.get('error', '?')})"
            print(f"{indent}+{elapsed:>5.1f}s  {source:<18} TOOL     {tool_name}  {latency:.0f}ms  {status}")
            if not success:
                failures.append({
                    "type": "tool",
                    "source": source,
                    "tool": tool_name,
                    "error": data.get("error", "?"),
                    "elapsed_s": elapsed,
                })
        elif etype == "task_delegated":
            delegations += 1
            target = data.get("target", "?")
            task_preview = (data.get("task") or "")[:45]
            print(f"{indent}+{elapsed:>5.1f}s  {source:<18} DELEGATE → {target}  \"{task_preview}\"")
        elif etype == "memory_updated":
            memory_ops += 1
            scope = data.get("scope", "?")
            content = (data.get("content") or "")[:50]
            print(f"{indent}+{elapsed:>5.1f}s  {source:<18} MEMORY   scope={scope}  \"{content}\"")

    # Summary
    print(f"\nSummary")
    print(_HR)

    session_ts = session_open.get("ts", "?") if session_open else "?"
    duration = session_close.get("elapsed_s", 0.0) if session_close else (events[-1].get("elapsed_s", 0.0) if events else 0.0)

    print(f"  Session start : {session_ts}")
    print(f"  Duration      : {duration:.1f}s")
    print(f"  Agents active : {', '.join(sorted(agents_active)) or 'none'}")
    print(f"  LLM calls     : {llm_calls}")
    print(f"  Tool calls    : {tool_calls}  (failed: {tool_failures})")
    print(f"  Delegations   : {delegations}")
    print(f"  Memory ops    : {memory_ops}")
    print(f"  Tokens in/out : {total_in} / {total_out}")

    if failures:
        print(f"\nFailures")
        print(_HR)
        for f in failures:
            if f["type"] == "agent":
                print(f"  +{f['elapsed_s']:>5.1f}s  AGENT FAILED  {f['source']}  {f['error']}")
            else:
                print(f"  +{f['elapsed_s']:>5.1f}s  TOOL FAILED   {f['source']}/{f['tool']}  {f['error']}")
