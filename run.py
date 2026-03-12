#!/usr/bin/env python3
"""CLI entry point for the LiteLLM Agent Engine."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from engine import Engine


async def _run_task(engine: Engine, agent: str, task: str) -> int:
    await engine._ensure_initialized()
    result = await engine.run_task(agent, task)
    print(result.result)
    await engine.close()
    return 1 if result.error else 0


async def _run_interactive(engine: Engine, agent: str) -> None:
    await engine.run_interactive(agent)


async def _run_parallel(engine: Engine, tasks: list[str]) -> int:
    await engine._ensure_initialized()
    manager = engine.enable_manager()

    run_ids = []
    for spec in tasks:
        if ":" not in spec:
            print(f"[Error] Invalid format: '{spec}'. Use 'agent:task'.")
            await engine.close()
            return 1
        agent_slug, task = spec.split(":", 1)
        run_id = await manager.submit(agent_slug.strip(), task.strip())
        run_ids.append(run_id)

    results = await manager.wait_all(run_ids)
    exit_code = 0
    for rid, result in zip(run_ids, results):
        run = manager.get_run(rid)
        label = f"[{run.agent_slug}]" if run else f"[{rid}]"
        if result and result.succeeded:
            print(f"{label} {result.result}")
        elif result:
            print(f"{label} [ERROR] {result.error}")
            exit_code = 1
        else:
            print(f"{label} [ERROR] No result")
            exit_code = 1

    await engine.close()
    return exit_code


def _print_trace(path, records: list[dict]) -> None:
    _HR = "─" * 70

    # Find session_open record for start time
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


def _cmd_show_trace(file_arg: str | None) -> None:
    from config import TRACES_DIR
    from pathlib import Path as _Path

    if file_arg:
        path = _Path(file_arg)
    else:
        files = sorted(TRACES_DIR.glob("*.jsonl")) if TRACES_DIR.exists() else []
        if not files:
            print("[show-trace] No trace files found in traces/", file=sys.stderr)
            sys.exit(1)
        path = files[-1]  # most recent (names are timestamped)

    if not path.exists():
        print(f"[show-trace] File not found: {path}", file=sys.stderr)
        sys.exit(1)

    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # skip corrupt lines

    if not records:
        print("[show-trace] Empty or unreadable trace file.", file=sys.stderr)
        sys.exit(1)

    _print_trace(path, records)


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "show-trace":
        _cmd_show_trace(sys.argv[2] if len(sys.argv) > 2 else None)
        return

    parser = argparse.ArgumentParser(
        description="Copper-Town LiteLLM Agent Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python run.py                          # interactive with Mini Me
  python run.py accounting               # interactive with Accounting
  python run.py -t "process receipt"     # single-task mode
  python run.py --parallel "accounting:process receipt" "google-workspace:list files"
  python run.py --list-agents            # show available agents
  python run.py --list-tools             # show available tools
  python run.py --verbose -t "task"      # stream trace events to stderr
  python run.py --trace -t "task"        # write trace file silently
  python run.py show-trace               # inspect most recent trace
  MODEL=gpt-4o python run.py            # different provider
""",
    )
    parser.add_argument(
        "agent",
        nargs="?",
        default="mini-me",
        help="Agent to use (default: mini-me)",
    )
    parser.add_argument(
        "-t", "--task",
        help="Run a single task (non-interactive mode)",
    )
    parser.add_argument(
        "--parallel",
        nargs="+",
        metavar="AGENT:TASK",
        help="Run multiple agent:task pairs concurrently",
    )
    parser.add_argument(
        "--list-agents",
        action="store_true",
        help="List all available agents",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List all registered tools",
    )
    parser.add_argument(
        "--model",
        help="Override the MODEL env var",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Stream trace events to stderr in real-time",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Write trace file silently; print path at end",
    )

    args = parser.parse_args()
    engine = Engine(model=args.model)

    if args.list_agents:
        agents = engine.list_agents()
        if not agents:
            print("No agents found in agents/")
            sys.exit(1)
        print(f"{'Slug':<20} {'Name':<20} {'Description'}")
        print("-" * 70)
        for a in agents:
            print(f"{a['slug']:<20} {a['name']:<20} {a['description'][:50]}")
            if a["tools"]:
                print(f"{'':>20} tools: {', '.join(a['tools'])}")
            if a["delegates_to"]:
                print(f"{'':>20} delegates to: {', '.join(a['delegates_to'])}")
            if a["skills"]:
                print(f"{'':>20} skills: {', '.join(a['skills'])}")
        return

    if args.list_tools:
        tools = engine.registry.list_tools()
        if not tools:
            print("No tools registered.")
            sys.exit(1)
        print(f"{'Tool':<30} {'Description'}")
        print("-" * 70)
        for name in tools:
            schema = engine.registry.get_schema(name)
            desc = schema["function"]["description"][:50] if schema else ""
            print(f"{name:<30} {desc}")
        return

    from tracer import SessionTracer
    tracer = SessionTracer(
        engine.event_bus,
        args.agent,
        verbose=args.verbose,
        silent_trace=args.trace and not args.verbose,
    )
    try:
        if args.parallel:
            exit_code = asyncio.run(_run_parallel(engine, args.parallel))
            sys.exit(exit_code)
        if args.task:
            exit_code = asyncio.run(_run_task(engine, args.agent, args.task))
            sys.exit(exit_code)
        asyncio.run(_run_interactive(engine, args.agent))
    finally:
        if tracer:
            tracer.close()


if __name__ == "__main__":
    main()
