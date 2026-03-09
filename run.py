#!/usr/bin/env python3
"""CLI entry point for the LiteLLM Agent Engine."""

from __future__ import annotations

import argparse
import json
import sys

from engine import Engine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copper-Town LiteLLM Agent Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python run.py                        # interactive with Mini Me
  python run.py accounting             # interactive with Accounting
  python run.py -t "process receipt"   # single-task mode
  python run.py --list-agents          # show available agents
  python run.py --list-tools           # show available tools
  MODEL=gpt-4o python run.py          # different provider
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

    if args.task:
        result = engine.run_task(args.agent, args.task)
        print(result)
        return

    engine.run_interactive(args.agent)


if __name__ == "__main__":
    main()
