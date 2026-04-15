"""REPLSession: interactive prompt/spinner/slash-command UI extracted from Engine."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .events import EventType
from .terminal import BOLD, CYAN, DIM, GREEN, RESET, YELLOW

if TYPE_CHECKING:
    from .engine import Engine
    from .events import Event


class REPLSession:
    """Interactive REPL for a single agent. Engine.run_interactive delegates here."""

    def __init__(self, engine: "Engine", agent_slug: str) -> None:
        self._engine = engine
        self._agent_slug = agent_slug
        self._messages: list[dict] = []
        self._agent = None  # set during run()

    # ── Slash commands ────────────────────────────────────────────────

    async def _cmd_help(self, _raw: str) -> None:
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

    async def _cmd_tasks(self, _raw: str) -> None:
        bg = self._engine._bg
        if not bg.has_tasks:
            print("  No active background tasks.\n")
        else:
            for tid, meta in bg.active_meta().items():
                print(f"  {tid}  [{meta.get('agent', '?')}]")
                print(f"    {meta.get('task', '?')}\n")

    async def _cmd_memory(self, _raw: str) -> None:
        entries = await self._engine.memory_store.get_memories(self._agent.slug)
        if not entries:
            print("  No memory entries.\n")
        else:
            for e in entries:
                pin = "[pinned] " if e.pinned else ""
                print(f"  #{e.id} {pin}{e.content}\n")

    async def _cmd_agents(self, _raw: str) -> None:
        for a in self._engine.agents.values():
            delegates = f" → {', '.join(a.delegates_to)}" if a.delegates_to else ""
            print(f"  {a.slug}  {a.name}{delegates}")
            print(f"    {a.description}\n")

    async def _cmd_clear(self, _raw: str) -> None:
        self._messages[:] = [self._messages[0]]
        print("  Conversation cleared.\n")

    async def _cmd_model(self, raw: str) -> None:
        from .config import validate_env
        parts = raw.split(maxsplit=1)
        if len(parts) == 1:
            print(f"  Current model: {self._engine.model}\n")
        else:
            new_model = parts[1].strip()
            try:
                validate_env(new_model)
                self._engine.model = new_model
                print(f"  Model set to: {self._engine.model}\n")
            except SystemExit:
                print("  Invalid model — missing API key.\n")

    async def _cmd_cancel(self, raw: str) -> None:
        bg = self._engine._bg
        parts = raw.split(maxsplit=1)
        task_id = parts[1].strip() if len(parts) > 1 else None
        if not task_id:
            if not bg.has_tasks:
                print("  No active background tasks.\n")
                return
            ids = bg.active_ids()
            if len(ids) == 1:
                task_id = ids[0]
            else:
                print("  Active tasks:")
                for tid, meta in bg.active_meta().items():
                    print(f"    {tid}: {meta.get('task', '?')[:80]}")
                print("  Usage: /cancel <task_id>\n")
                return
        result = json.loads(await self._engine._handle_cancel_background({"task_id": task_id}))
        status = result.get("status", "")
        msg = {
            "cancelled": f"  Cancelled {task_id}.\n",
            "already_completed": f"  {task_id} already completed — nothing to cancel.\n",
        }.get(status)
        print(msg or f"  {result.get('error', result)}\n")

    # ── UI helpers ────────────────────────────────────────────────────

    def _agent_display_name(self, slug: str) -> str:
        agents = self._engine.agents
        return agents[slug].name if slug in agents else slug

    @staticmethod
    def _print_agent_tree(names: list[str], verb: str, detail: str | None = None, indent: str = "") -> None:
        n = len(names)
        label = "agent" if n == 1 else "agents"
        print(f"\n{indent}{BOLD}{GREEN}● {n} {label} {verb}{RESET}")
        for i, name in enumerate(names):
            is_last = i == n - 1
            connector = "└──" if is_last else "├──"
            print(f"{indent}{connector} {BOLD}{name}{RESET}")
            if detail:
                sub_indent = "    " if is_last else "│   "
                print(f"{indent}{sub_indent}{DIM}└ {detail}{RESET}")
        print()

    def _print_task_tree(self, new_ids: list[str]) -> None:
        names = [
            self._agent_display_name(self._engine._bg.get_meta(tid).get("agent", "?"))
            for tid in new_ids
        ]
        self._print_agent_tree(names, "launched", "Running in the background")

    # ── Main loop ─────────────────────────────────────────────────────

    async def run(self) -> None:
        from rich.console import Console
        from rich.markdown import Markdown
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import ANSI
        from prompt_toolkit.history import FileHistory
        from .engine import _hallucination_fired, _last_usage

        engine = self._engine
        agent = engine.agents.get(self._agent_slug)
        if not agent:
            print(f"[Error] Agent '{self._agent_slug}' not found.")
            print(f"Available agents: {', '.join(engine.agents.keys())}")
            return

        self._agent = agent
        system_prompt = await engine._build_system_prompt(agent)
        self._messages = [{"role": "system", "content": system_prompt}]
        messages = self._messages

        console = Console()
        console.print(f"🤖 [bold green]{agent.name}[/bold green] ready. (model: {engine.model})")
        console.print("Type 'quit' or 'exit' to end the session.\n")

        agent_label = BOLD + GREEN + f"● {agent.name}: " + RESET
        pt_session = PromptSession(history=FileHistory(str(Path.home() / ".copper_history")))

        slash_dispatch = {
            "/help": self._cmd_help,
            "/tasks": self._cmd_tasks,
            "/memory": self._cmd_memory,
            "/agents": self._cmd_agents,
            "/clear": self._cmd_clear,
            "/model": self._cmd_model,
            "/cancel": self._cmd_cancel,
        }

        def _get_prompt() -> ANSI:
            base = BOLD + CYAN + "● You: " + RESET
            if not engine._bg.has_tasks:
                return ANSI(base)
            n = len(engine._bg.active_ids())
            status = DIM + f"\u27f3 {n} background {'task' if n == 1 else 'tasks'} running" + RESET
            return ANSI(status + "\n\n" + base)

        _sync_agents: list[str] = []

        async def _on_task_delegated(event: Event) -> None:
            if event.source == agent.slug:
                _sync_agents.append(self._agent_display_name(event.data.get("target", "?")))

        _sub_del_buf: dict[str, list[str]] = {}
        _sub_del_verb: dict[str, str] = {}
        _sub_del_timers: dict[str, asyncio.Task] = {}

        async def _flush_sub_del(source_slug: str) -> None:
            await asyncio.sleep(0.1)
            targets = _sub_del_buf.pop(source_slug, [])
            verb = _sub_del_verb.pop(source_slug, "used")
            _sub_del_timers.pop(source_slug, None)
            if targets:
                with _pt_patch_stdout(raw=True):
                    self._print_agent_tree(targets, verb, indent="    ")

        async def _on_sub_delegation(event: Event) -> None:
            if event.source != agent.slug:
                source = event.source
                target_name = self._agent_display_name(event.data.get("target", "?"))
                _sub_del_buf.setdefault(source, []).append(target_name)
                _sub_del_verb[source] = "launched" if event.type == EventType.TASK_BACKGROUND_STARTED else "used"
                pending = _sub_del_timers.pop(source, None)
                if pending:
                    pending.cancel()
                _sub_del_timers[source] = asyncio.create_task(_flush_sub_del(source))

        engine.event_bus.subscribe(EventType.TASK_DELEGATED, _on_task_delegated)
        engine.event_bus.subscribe(EventType.TASK_DELEGATED, _on_sub_delegation)
        engine.event_bus.subscribe(EventType.TASK_BACKGROUND_STARTED, _on_sub_delegation)

        from prompt_toolkit.patch_stdout import patch_stdout as _pt_patch_stdout
        from prompt_toolkit.application import get_app_or_none as _get_app_or_none

        _AUTO_RESPOND = "\x00__auto__"

        def _on_bg_notification(note: str) -> None:
            lines = note.splitlines()
            header = lines[0] if lines else note
            meta = lines[1] if len(lines) > 1 else ""
            task_line = lines[2] if len(lines) > 2 else ""
            with _pt_patch_stdout(raw=True):
                print(f"\n{DIM}{header}{RESET}")
                if meta:
                    print(f"{DIM}{meta}{RESET}")
                if task_line:
                    print(f"{DIM}{task_line}{RESET}")
                print()
            # Auto-trigger a Captain response only if the user hasn't started typing
            app = _get_app_or_none()
            if app is not None:
                try:
                    if not app.current_buffer.text:
                        app.exit(result=_AUTO_RESPOND)
                except Exception:
                    pass

        engine._bg.on_notification = _on_bg_notification

        try:
            while True:
                try:
                    user_input = await pt_session.prompt_async(_get_prompt)
                    user_input = user_input.strip()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    continue

                # Drain notifications into messages for LLM context
                engine._bg.drain_into_messages(messages)

                auto_respond = user_input == _AUTO_RESPOND
                if not user_input and not auto_respond:
                    continue
                if user_input.lower() in ("quit", "exit"):
                    break

                cmd_key = user_input.split()[0].lower() if user_input.startswith("/") else None
                if cmd_key in slash_dispatch:
                    await slash_dispatch[cmd_key](user_input)
                    continue

                restore_len = len(messages)
                if not auto_respond:
                    messages.append({"role": "user", "content": user_input})

                accumulated = ""
                spinner_stopped = False
                tasks_before = set(engine._bg.active_ids())
                _sync_agents.clear()

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
                    del messages[restore_len:]
                    continue

                new_task_ids = [t for t in engine._bg.active_ids() if t not in tasks_before]

                elapsed = time.monotonic() - t0
                corrected = _hallucination_fired.get(False)
                final_text = response or accumulated

                print(f"\n{agent_label}")
                if corrected:
                    print(f"{DIM}[original — auto-corrected]{RESET}")
                    console.print(Markdown(accumulated))
                    print(f"{YELLOW}[corrected]{RESET}")
                if final_text:
                    console.print(Markdown(final_text))

                usage = _last_usage.get({"in": 0, "out": 0})
                token_info = (
                    "\033[2m"
                    + f"↑{usage['in']} ↓{usage['out']}  {elapsed:.1f}s"
                    + RESET
                )
                messages.append({"role": "assistant", "content": response})
                print(f"{token_info}\n")

                if new_task_ids:
                    self._print_task_tree(new_task_ids)

                if _sync_agents:
                    self._print_agent_tree(_sync_agents, "used")

        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n")
        finally:
            engine._bg.on_notification = None
            engine.event_bus.unsubscribe(EventType.TASK_DELEGATED, _on_task_delegated)
            engine.event_bus.unsubscribe(EventType.TASK_DELEGATED, _on_sub_delegation)
            engine.event_bus.unsubscribe(EventType.TASK_BACKGROUND_STARTED, _on_sub_delegation)
            for t in _sub_del_timers.values():
                t.cancel()
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
