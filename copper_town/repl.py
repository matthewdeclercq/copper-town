"""REPLSession: interactive prompt/spinner/slash-command UI extracted from Engine."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .terminal import BOLD, CYAN, DIM, GREEN, RESET, YELLOW

if TYPE_CHECKING:
    from .engine import Engine


class REPLSession:
    """Interactive REPL for a single agent. Engine.run_interactive delegates here."""

    def __init__(self, engine: "Engine", agent_slug: str) -> None:
        self._engine = engine
        self._agent_slug = agent_slug

    async def run(self) -> None:
        from rich.console import Console
        from rich.markdown import Markdown
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import ANSI
        from prompt_toolkit.history import FileHistory

        engine = self._engine
        agent_slug = self._agent_slug

        agent = engine.agents.get(agent_slug)
        if not agent:
            print(f"[Error] Agent '{agent_slug}' not found.")
            print(f"Available agents: {', '.join(engine.agents.keys())}")
            return

        system_prompt = await engine._build_system_prompt(agent)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        console = Console()
        console.print(f"🤖 [bold green]{agent.name}[/bold green] ready. (model: {engine.model})")
        console.print("Type 'quit' or 'exit' to end the session.\n")

        agent_label = BOLD + GREEN + f"● {agent.name}: " + RESET
        pt_session = PromptSession(history=FileHistory(str(Path.home() / ".copper_history")))

        # Slash-command dispatch table — each handler returns True to continue REPL loop.
        async def _cmd_help(_: str) -> bool:
            print(
                "  Slash commands:\n"
                "    /help               Show this message\n"
                "    /tasks              List active background tasks with full descriptions\n"
                "    /cancel [task_id]   Cancel a background task (omit task_id if only one active)\n"
                "    /memory             Show this agent's memory entries\n"
                "    /agents             List all available agents\n"
                "    /clear              Clear conversation history (keeps system prompt)\n"
                "    /model [name]       Show current model, or switch to a new one\n"
            )
            return True

        async def _cmd_tasks(_: str) -> bool:
            if not engine._bg.has_tasks:
                print("  No active background tasks.\n")
            else:
                for tid, meta in engine._bg.active_meta().items():
                    print(f"  {tid}  [{meta.get('agent', '?')}]")
                    print(f"    {meta.get('task', '?')}\n")
            return True

        async def _cmd_memory(_: str) -> bool:
            entries = await engine.memory_store.get_memories(agent.slug)
            if not entries:
                print("  No memory entries.\n")
            else:
                for e in entries:
                    pin = "[pinned] " if e.pinned else ""
                    print(f"  #{e.id} {pin}{e.content}\n")
            return True

        async def _cmd_agents(_: str) -> bool:
            for a in engine.agents.values():
                delegates = f" → {', '.join(a.delegates_to)}" if a.delegates_to else ""
                print(f"  {a.slug}  {a.name}{delegates}")
                print(f"    {a.description}\n")
            return True

        async def _cmd_clear(_: str) -> bool:
            nonlocal messages
            messages = [messages[0]]
            print("  Conversation cleared.\n")
            return True

        async def _cmd_model(raw: str) -> bool:
            from .config import validate_env
            parts = raw.split(maxsplit=1)
            if len(parts) == 1:
                print(f"  Current model: {engine.model}\n")
            else:
                new_model = parts[1].strip()
                try:
                    validate_env(new_model)
                    engine.model = new_model
                    print(f"  Model set to: {engine.model}\n")
                except SystemExit:
                    print("  Invalid model — missing API key.\n")
            return True

        async def _cmd_cancel(raw: str) -> bool:
            parts = raw.split(maxsplit=1)
            task_id = parts[1].strip() if len(parts) > 1 else None
            if not task_id:
                if not engine._bg.has_tasks:
                    print("  No active background tasks.\n")
                    return True
                ids = engine._bg.active_ids()
                if len(ids) == 1:
                    task_id = ids[0]
                else:
                    print("  Active tasks:")
                    for tid, meta in engine._bg.active_meta().items():
                        print(f"    {tid}: {meta.get('task', '?')[:80]}")
                    print("  Usage: /cancel <task_id>\n")
                    return True
            result = json.loads(await engine._handle_cancel_background({"task_id": task_id}))
            if result.get("status") == "cancelled":
                print(f"  Cancelled {task_id}.\n")
            elif result.get("status") == "already_completed":
                print(f"  {task_id} already completed — nothing to cancel.\n")
            else:
                print(f"  {result.get('error', result)}\n")
            return True

        _slash_dispatch = {
            "/help": _cmd_help,
            "/tasks": _cmd_tasks,
            "/memory": _cmd_memory,
            "/agents": _cmd_agents,
            "/clear": _cmd_clear,
        }

        def _get_prompt() -> ANSI:
            base = BOLD + CYAN + "● You: " + RESET
            if not engine._bg.has_tasks:
                return ANSI(base)
            parts = []
            for task_id, meta in engine._bg.active_meta().items():
                slug = meta.get("agent", "?")
                name = engine.agents[slug].name if slug in engine.agents else slug
                parts.append(f"{name} ({task_id})")
            n = len(engine._bg.active_ids())
            status = f" \u27f3 {n} background {'task' if n == 1 else 'tasks'}: {', '.join(parts)}"
            return ANSI(status + "\n\n" + base)

        try:
            while True:
                try:
                    user_input = await pt_session.prompt_async(_get_prompt)
                    user_input = user_input.strip()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    continue

                # Drain background task notifications before each turn
                pending = engine._bg.drain_notifications()
                if pending:
                    for note in pending:
                        lines = note.splitlines()
                        print(f"\n\033[2m{lines[0]} — {lines[1] if len(lines) > 1 else ''}\033[0m")
                    print()
                    if len(pending) == 1:
                        messages.append({"role": "system", "content": pending[0]})
                    else:
                        bundled = "\n\n---\n\n".join(pending)
                        messages.append({"role": "system", "content": f"[{len(pending)} background tasks completed]\n\n{bundled}"})

                if not user_input:
                    continue
                if user_input.lower() in ("quit", "exit"):
                    break

                # Prefix-matched slash commands (/cancel, /model take args)
                cmd_key = user_input.lower().split()[0] if user_input.startswith("/") else None
                if cmd_key in ("/cancel", "/model"):
                    handler = _cmd_cancel if cmd_key == "/cancel" else _cmd_model
                    await handler(user_input)
                    continue
                if cmd_key and cmd_key in _slash_dispatch:
                    await _slash_dispatch[cmd_key](user_input)
                    continue

                messages.append({"role": "user", "content": user_input})

                accumulated = ""
                spinner_stopped = False

                def on_token(chunk: str) -> None:
                    nonlocal accumulated, spinner_stopped
                    if not spinner_stopped:
                        stop_fn()
                        spinner_stopped = True
                    accumulated += chunk

                t0 = time.monotonic()
                try:
                    async with engine._spinner(agent.name) as stop_fn:
                        response = await engine._completion_loop(
                            agent, messages, depth=0, on_token=on_token
                        )
                except Exception as e:
                    print(f"\n[Error] {e}. Session preserved — type another message.\n")
                    messages.pop()
                    continue

                elapsed = time.monotonic() - t0
                # If hallucination correction fired, response differs from accumulated.
                # Show the original (dimmed) so the user can still see what the agent said.
                corrected = (
                    accumulated
                    and response
                    and accumulated.strip() != response.strip()
                )
                final_text = response or accumulated

                print(f"\n{agent_label}")
                if corrected:
                    print(f"{DIM}[original — auto-corrected]{RESET}")
                    console.print(Markdown(accumulated))
                    print(f"{YELLOW}[corrected]{RESET}")
                if final_text:
                    console.print(Markdown(final_text))

                from .engine import _last_usage
                usage = _last_usage.get({"in": 0, "out": 0})
                token_info = (
                    "\033[2m"
                    + f"↑{usage['in']} ↓{usage['out']}  {elapsed:.1f}s"
                    + RESET
                )
                messages.append({"role": "assistant", "content": response})
                print(f"{token_info}\n")

        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n")
        finally:
            if engine._bg.has_tasks:
                remaining = engine._bg.all_tasks()
                for bg_task in remaining:
                    bg_task.cancel()
                await asyncio.gather(*remaining, return_exceptions=True)
                print(f"[{len(remaining)} background task(s) cancelled on exit.]")
            async with engine._spinner("Saving memory") as _stop:
                await engine._extract_session_memory(agent, messages)
            await engine.close()
            print("Session ended.")
