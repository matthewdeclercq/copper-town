#!/usr/bin/env python3
"""CLI entry point for the LiteLLM Agent Engine."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from copper_town.engine import Engine


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


def _cmd_show_trace(file_arg: str | None) -> None:
    from copper_town.config import TRACES_DIR
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

    from copper_town.tracer import format_trace
    format_trace(path, records)


async def _cmd_regen_gws_skills(filter_names: list[str] | None) -> None:
    from copper_town.tools.regen_gws_skills import regen_gws_skills
    results = await regen_gws_skills(filter_names=filter_names)
    updated = [r for r in results if r["status"] == "updated"]
    errors = [r for r in results if r["status"] == "error"]
    print(f"\nRegenerated {len(updated)}/{len(results)} skills.")
    for e in errors:
        print(f"  [ERROR] {e['skill']}: {e['error']}")


async def _cmd_serve() -> None:
    from copper_town.config import API_HOST, API_PORT, ROOT_DIR
    from copper_town.tracer import SessionTracer

    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    model = None
    for i, arg in enumerate(sys.argv):
        if arg == "--model" and i + 1 < len(sys.argv):
            model = sys.argv[i + 1]

    engine = Engine(model=model)
    await engine._ensure_initialized()
    tracer = SessionTracer(
        engine.event_bus,
        "serve",
        verbose=verbose,
        silent_trace=True,
    )

    from copper_town.api import create_app
    from starlette.staticfiles import StaticFiles
    import uvicorn

    app = create_app(engine)
    web_dir = ROOT_DIR / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")

    config = uvicorn.Config(app, host=API_HOST, port=API_PORT, log_level="info")
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        tracer.close()
        await engine.close()


async def _cmd_daemon() -> None:
    import signal
    from copper_town.scheduler import Scheduler
    from copper_town.tracer import SessionTracer

    # Parse daemon-specific flags from argv (not routed through argparse)
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    model = None
    for i, arg in enumerate(sys.argv):
        if arg == "--model" and i + 1 < len(sys.argv):
            model = sys.argv[i + 1]
    engine = Engine(model=model)
    tracer = SessionTracer(
        engine.event_bus,
        "daemon",
        verbose=verbose,
        silent_trace=True,
    )
    scheduler = Scheduler(engine)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, scheduler.request_shutdown)

    try:
        await scheduler.run()
    finally:
        tracer.close()
        await engine.close()


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "show-trace":
        _cmd_show_trace(sys.argv[2] if len(sys.argv) > 2 else None)
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "regen-gws-skills":
        filter_names = sys.argv[2:] if len(sys.argv) > 2 else None
        asyncio.run(_cmd_regen_gws_skills(filter_names))
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "serve":
        asyncio.run(_cmd_serve())
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "daemon":
        asyncio.run(_cmd_daemon())
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
  python run.py regen-gws-skills        # regenerate all gws skill files
  python run.py regen-gws-skills gmail  # regenerate only gmail skills
  python run.py daemon                   # run scheduler daemon
  python run.py daemon -v                # scheduler with verbose trace output
  python run.py serve                    # start HTTP API + PWA server
  python run.py serve -v                 # serve with verbose trace output
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

    from copper_town.tracer import SessionTracer
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
        asyncio.run(engine.close())


if __name__ == "__main__":
    main()
