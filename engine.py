"""Core engine: agent loading, tool dispatch, completion loop, delegation."""

from __future__ import annotations

import atexit
import concurrent.futures
import os
import itertools
import json
import logging
import re
import readline  # noqa: F401 — enables option+backspace, cmd+backspace in input()
import signal
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import litellm
import yaml

from config import (
    AGENTS_DIR,
    ALLOWED_READ_DIRS,
    CONTEXT_SUMMARIZE,
    GLOBAL_SKILLS_DIR,
    LOG_LEVEL,
    MAX_CONTEXT_MESSAGES,
    MAX_DELEGATION_DEPTH,
    MAX_PARALLEL_TOOLS,
    MAX_SYSTEM_PROMPT_CHARS,
    MAX_TOOL_ITERATIONS,
    MAX_TOOL_OUTPUT_CHARS,
    MEMORY_COMPRESS_ENABLED,
    MEMORY_DIR,
    MEMORY_MAX_LINES,
    MEMORY_MIN_MESSAGES,
    MEMORY_WRITE_MAX_CHARS,
    MODEL,
    SKILLS_DIR,
)
from tools import ToolRegistry

logger = logging.getLogger("copper_town")


@dataclass
class AgentDefinition:
    """Parsed agent from a .md file with YAML frontmatter."""

    slug: str
    name: str
    description: str
    agent_dir: Path = field(default_factory=lambda: Path("."))
    tools: list[str] = field(default_factory=list)
    delegates_to: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    body: str = ""
    model: str | None = None
    memory_guidance: str = ""


class Engine:
    """LiteLLM-powered agent engine with tool calling, delegation, and memory."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or MODEL
        self.registry = ToolRegistry()
        self.agents: dict[str, AgentDefinition] = {}
        self._local = threading.local()
        logging.basicConfig(
            level=getattr(logging, LOG_LEVEL.upper(), logging.WARNING),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        self._mem_locks: dict[str, threading.Lock] = {}
        self._mem_locks_lock = threading.Lock()
        self._session_agent: AgentDefinition | None = None
        self._session_messages: list[dict] | None = None
        self._spinner_status: list[str] = [""]  # mutable; updated live during delegation
        self._load_all_agents()

    def _get_mem_lock(self, path: Path) -> threading.Lock:
        """Return (creating if needed) a per-file threading.Lock for memory writes."""
        key = str(path.resolve())
        with self._mem_locks_lock:
            if key not in self._mem_locks:
                self._mem_locks[key] = threading.Lock()
            return self._mem_locks[key]

    # ── Agent loading ──────────────────────────────────────────────

    def _load_all_agents(self) -> None:
        """Scan agents/*/agent.md and parse frontmatter + body."""
        if not AGENTS_DIR.exists():
            return
        for path in sorted(AGENTS_DIR.glob("*/agent.md")):
            agent = self._parse_agent_file(path)
            if agent:
                self.agents[agent.slug] = agent
        self._name_to_slug: dict[str, str] = {
            a.name.lower().replace(" ", "-"): a.slug
            for a in self.agents.values()
        }

    @staticmethod
    def _parse_agent_file(path: Path) -> AgentDefinition | None:
        """Parse a markdown file with YAML frontmatter."""
        text = path.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not match:
            return None
        front = yaml.safe_load(match.group(1)) or {}
        body = match.group(2).strip()
        agent_dir = path.parent
        return AgentDefinition(
            slug=agent_dir.name,
            name=front.get("name", agent_dir.name),
            description=front.get("description", ""),
            agent_dir=agent_dir,
            tools=front.get("tools", []),
            delegates_to=front.get("delegates_to", []),
            skills=front.get("skills", []),
            body=body,
            model=front.get("model"),
            memory_guidance=front.get("memory_guidance", ""),
        )

    # ── System prompt assembly ─────────────────────────────────────

    @staticmethod
    def _sanitize_memory(text: str) -> str:
        """Sanitize memory content before injecting into system prompts.

        - Removes bare separator lines (--- or more dashes) to prevent prompt structure breaks.
        - Demotes markdown headings by wrapping in brackets so they aren't parsed as sections.
        - Collapses 3+ consecutive blank lines to 2.
        """
        lines = text.splitlines()
        sanitized = []
        for line in lines:
            if re.match(r"^-{3,}\s*$", line):
                continue  # drop bare separator lines
            line = re.sub(r"^(#{1,6}\s)", r"[\1", line)
            if line.startswith("[#"):
                line = line + "]"
            sanitized.append(line)
        # Collapse 3+ blank lines to 2
        result = re.sub(r"\n{3,}", "\n\n", "\n".join(sanitized))
        return result

    @staticmethod
    def _interpolate_env(text: str) -> str:
        """Replace ${VAR_NAME} placeholders with environment variable values."""
        return re.sub(
            r"\$\{(\w+)\}",
            lambda m: os.getenv(m.group(1), m.group(0)),
            text,
        )

    def _build_system_prompt(self, agent: AgentDefinition) -> str:
        """Assemble agent body + skills + memory into a system prompt."""
        parts: list[str] = [self._interpolate_env(agent.body)]

        # Global skills
        if GLOBAL_SKILLS_DIR.exists():
            for skill_path in sorted(GLOBAL_SKILLS_DIR.glob("*.md")):
                content = skill_path.read_text(encoding="utf-8").strip()
                if content:
                    content = self._interpolate_env(content)
                    parts.append(f"\n\n---\n## Skill: {skill_path.stem}\n\n{content}")

        # Agent-specific skills (search entire skills tree)
        for skill_name in agent.skills:
            matches = list(SKILLS_DIR.rglob(f"{skill_name}.md"))
            skill_path = matches[0] if matches else None
            if skill_path:
                raw = skill_path.read_text(encoding="utf-8").strip()
                # Strip frontmatter from skill
                m = re.match(r"^---\s*\n.*?\n---\s*\n(.*)", raw, re.DOTALL)
                content = m.group(1).strip() if m else raw
                content = self._interpolate_env(content)
                parts.append(f"\n\n---\n## Skill: {skill_name}\n\n{content}")

        # Memory: global + per-agent
        global_mem = MEMORY_DIR / "global.md"
        if global_mem.exists():
            mem = self._sanitize_memory(global_mem.read_text(encoding="utf-8").strip())
            if mem:
                parts.append(f"\n\n---\n## Memory (global)\n\n{mem}")

        agent_mem = agent.agent_dir / "memory.md"
        if agent_mem.exists():
            mem = self._sanitize_memory(agent_mem.read_text(encoding="utf-8").strip())
            if mem:
                parts.append(f"\n\n---\n## Memory ({agent.name})\n\n{mem}")

        result = "\n".join(parts)
        if len(result) > MAX_SYSTEM_PROMPT_CHARS:
            logger.warning(
                "System prompt for agent '%s' is %d chars (limit %d). "
                "Consider reducing injected skills or memory.",
                agent.slug, len(result), MAX_SYSTEM_PROMPT_CHARS,
            )
        return result

    # ── Tool resolution ────────────────────────────────────────────

    def _resolve_tools(
        self, agent: AgentDefinition, depth: int
    ) -> list[dict]:
        """Collect tool schemas for the agent."""
        tool_names = list(agent.tools)

        # Always-on tools
        for t in ("remember", "search_skills", "load_skill"):
            if t not in tool_names:
                tool_names.append(t)

        # Delegation tool if allowed and not at max depth
        include_delegation = agent.delegates_to and depth < MAX_DELEGATION_DEPTH
        if include_delegation and "delegate_to_agent" not in tool_names:
            tool_names.append("delegate_to_agent")

        schemas = self.registry.get_schemas(tool_names)

        # Patch delegate_to_agent description with valid targets for this agent
        if include_delegation:
            valid_slugs = ", ".join(agent.delegates_to)
            for schema in schemas:
                if schema.get("function", {}).get("name") == "delegate_to_agent":
                    schema["function"]["description"] = (
                        f"Delegate a task to a sub-agent. "
                        f"Valid targets for this agent: {valid_slugs}"
                    )
                    break

        return schemas

    # ── Terminal colors ────────────────────────────────────────────

    _RESET  = "\033[0m"
    _BOLD   = "\033[1m"
    _CYAN   = "\033[96m"   # user
    _GREEN  = "\033[92m"   # agent

    @staticmethod
    def _c(text: str, *codes: str) -> str:
        return "".join(codes) + text + Engine._RESET

    # ── Spinner ────────────────────────────────────────────────────

    @contextmanager
    def _spinner(self, message: str = "Thinking"):
        """Display an animated spinner on stdout while a block executes."""
        self._spinner_status[0] = message
        stop = threading.Event()

        def spin() -> None:
            frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            for frame in itertools.cycle(frames):
                if stop.is_set():
                    break
                msg = self._spinner_status[0]
                sys.stdout.write(f"\r{frame} {msg}...")
                sys.stdout.flush()
                stop.wait(0.1)
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()

        t = threading.Thread(target=spin, daemon=True)
        t.start()
        try:
            yield
        finally:
            stop.set()
            t.join()

    # ── LLM call ───────────────────────────────────────────────────

    def _call_llm(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        model: str | None = None,
    ) -> Any:
        """Call LiteLLM with optional tool definitions. Retries on transient errors."""
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                return litellm.completion(**kwargs)
            except (litellm.RateLimitError, litellm.APIConnectionError) as e:
                last_exc = e
                time.sleep(2 ** attempt)
        raise last_exc  # type: ignore[misc]

    # ── Tool execution ─────────────────────────────────────────────

    def _execute_tool_call(
        self,
        tool_call: Any,
        agent: AgentDefinition,
        depth: int,
        allowed_tools: set[str] | None = None,
    ) -> str:
        """Dispatch a tool call to its handler."""
        name = tool_call.function.name

        if allowed_tools is not None and name not in allowed_tools:
            return json.dumps({"error": f"Tool '{name}' is not authorized for agent '{agent.name}'."})

        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in tool arguments"})

        # Intercept delegation
        if name == "delegate_to_agent":
            result = self._handle_delegation(args, agent, depth, allowed_tools)
        elif name == "remember":
            result = self._handle_remember(args, agent)
        else:
            result = self.registry.execute(name, args)

        logger.debug("Tool '%s' returned %d chars", name, len(result))

        if len(result) > MAX_TOOL_OUTPUT_CHARS:
            trimmed = len(result) - MAX_TOOL_OUTPUT_CHARS
            result = result[:MAX_TOOL_OUTPUT_CHARS] + f"... [truncated {trimmed} chars]"

        return result

    def _handle_delegation(
        self, args: dict, agent: AgentDefinition, depth: int, allowed_tools: set[str] | None = None
    ) -> str:
        """Validate and execute delegation to a sub-agent."""
        raw_target = args.get("agent", "")
        task = args.get("task", "")
        context = args.get("context", "")

        # Resolve target slug: exact match → name lookup → error
        if raw_target in agent.delegates_to:
            target_slug = raw_target
        else:
            normalized = raw_target.lower().replace(" ", "-")
            via_name = self._name_to_slug.get(normalized)
            if via_name and via_name in agent.delegates_to:
                target_slug = via_name
            else:
                valid = ", ".join(
                    f"{s} ({self.agents[s].name})" if s in self.agents else s
                    for s in agent.delegates_to
                )
                return json.dumps({
                    "error": (
                        f"Agent '{agent.name}' cannot delegate to '{raw_target}'. "
                        f"Valid targets: {valid}"
                    )
                })

        if target_slug not in self.agents:
            return json.dumps({"error": f"Agent '{target_slug}' not found."})

        if depth >= MAX_DELEGATION_DEPTH:
            return json.dumps({"error": "Maximum delegation depth reached."})

        if not hasattr(self._local, "delegation_chain"):
            self._local.delegation_chain = []
        self._local.delegation_chain.append(agent.slug)
        chain_str = " → ".join(self._local.delegation_chain + [target_slug])
        logger.info("Delegation start: %s (depth=%d, chain: %s)", target_slug, depth + 1, chain_str)
        self._spinner_status[0] = chain_str
        try:
            result = self.run_task(target_slug, task, depth=depth + 1, context=context)
        finally:
            self._local.delegation_chain.pop()
            # Restore spinner to parent agent name
            self._spinner_status[0] = agent.name
        logger.info("Delegation end: %s, result size=%d chars", target_slug, len(result))
        return json.dumps({"agent": target_slug, "result": result})

    def _handle_remember(self, args: dict, agent: AgentDefinition) -> str:
        """Append content to the appropriate memory file."""
        content = args.get("content", "").strip()
        scope = args.get("scope", "agent")

        if not content:
            return json.dumps({"error": "No content provided to remember."})

        # Collapse multi-line content to a single line (prevents header injection)
        content = " ".join(content.splitlines())
        # Enforce size cap
        if len(content) > MEMORY_WRITE_MAX_CHARS:
            content = content[:MEMORY_WRITE_MAX_CHARS] + "... [truncated]"

        if scope == "global":
            mem_path = MEMORY_DIR / "global.md"
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        else:
            mem_path = agent.agent_dir / "memory.md"

        lock = self._get_mem_lock(mem_path)
        with lock:
            with open(mem_path, "a", encoding="utf-8") as f:
                f.write(f"\n- {content}\n")
            self._maybe_compress_memory(mem_path)
            current_memory = mem_path.read_text(encoding="utf-8").strip()

        logger.debug("Memory write: agent='%s', scope='%s'", agent.slug, scope)
        return json.dumps({
            "saved": True,
            "scope": scope,
            "file": str(mem_path),
            "current_memory": current_memory,
        })

    # ── Memory compression ─────────────────────────────────────────

    def _maybe_compress_memory(self, mem_path: Path) -> None:
        """If memory file exceeds MEMORY_MAX_LINES, deduplicate via LLM.

        WARNING: compression sends the full memory file contents to the configured
        LLM provider. If memory contains sensitive data (credentials, PII), set
        MEMORY_COMPRESS_ENABLED=false in your .env to disable this behaviour.
        """
        if not mem_path.exists():
            return
        lines = mem_path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= MEMORY_MAX_LINES:
            return
        if not MEMORY_COMPRESS_ENABLED:
            logger.debug("Memory compression disabled (MEMORY_COMPRESS_ENABLED=false); skipping.")
            return
        logger.warning(
            "Compressing memory file '%s' (%d lines). "
            "File contents will be sent to the LLM provider for deduplication. "
            "Set MEMORY_COMPRESS_ENABLED=false to disable.",
            mem_path, len(lines),
        )
        prompt = (
            "The following is a memory file with accumulated facts. "
            "Deduplicate, remove contradictions, and consolidate into a clean bullet list. "
            "Keep all unique facts. Return ONLY the bullet list.\n\n"
            + mem_path.read_text(encoding="utf-8")
        )
        try:
            response = self._call_llm(
                [{"role": "user", "content": prompt}], tools=None
            )
            compressed = response.choices[0].message.content.strip()
            mem_path.write_text(f"# Memory\n\n{compressed}\n", encoding="utf-8")
        except Exception:
            pass  # Don't crash if compression fails

    def _summarize_messages(self, to_trim: list[dict]) -> str | None:
        """LLM-summarize evicted messages. Returns None if disabled or on failure."""
        if not CONTEXT_SUMMARIZE or not to_trim:
            return None
        lines = []
        for msg in to_trim:
            role = msg.get("role", "unknown")
            content = msg.get("content") or ""
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                )
            lines.append(f"[{role}]: {content[:500]}")
        prompt = (
            "The following conversation segment is being removed from the active context window. "
            "Write a concise summary (3-5 sentences) of key facts, decisions, and tool results.\n\n"
            + "\n".join(lines)
        )
        try:
            response = self._call_llm([{"role": "user", "content": prompt}], tools=None)
            return response.choices[0].message.content.strip() or None
        except Exception:
            logger.debug("Context summarization failed; using generic notice.")
            return None

    # ── Completion loop ────────────────────────────────────────────

    def _completion_loop(
        self,
        agent: AgentDefinition,
        messages: list[dict],
        depth: int,
    ) -> str:
        """Call LLM → handle tool calls → loop until text response or safety cap."""
        tools = self._resolve_tools(agent, depth)
        allowed_tools: set[str] = {
            s["function"]["name"] for s in tools
        }
        self._local.last_usage = {"in": 0, "out": 0}

        last_tool: str | None = None

        for _ in range(MAX_TOOL_ITERATIONS):
            # Sliding context window with optional summarization
            if len(messages) > MAX_CONTEXT_MESSAGES + 1:
                keep_tail = messages[-(MAX_CONTEXT_MESSAGES):]
                to_trim = messages[1 : len(messages) - MAX_CONTEXT_MESSAGES]
                summary = self._summarize_messages(to_trim)
                notice_text = (
                    f"[Earlier context summarized: {summary}]" if summary
                    else "[Earlier context trimmed to stay within limits.]"
                )
                messages = [messages[0], {"role": "system", "content": notice_text}] + keep_tail
                logger.warning("Context trimmed for agent '%s': evicted %d messages.", agent.slug, len(to_trim))

            response = self._call_llm(messages, tools or None, model=agent.model)
            usage = getattr(response, "usage", None)
            if usage:
                self._local.last_usage["in"] += getattr(usage, "prompt_tokens", 0)
                self._local.last_usage["out"] += getattr(usage, "completion_tokens", 0)
            choice = response.choices[0]
            message = choice.message

            # If no tool calls, return text content
            if not message.tool_calls:
                return message.content or ""

            # Append assistant message with tool calls
            messages.append(message.model_dump())

            # Execute tool calls (parallel if multiple)
            tool_calls = message.tool_calls
            if len(tool_calls) == 1:
                tc = tool_calls[0]
                last_tool = tc.function.name
                result = self._execute_tool_call(tc, agent, depth, allowed_tools)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL_TOOLS) as executor:
                    futures = {
                        executor.submit(self._execute_tool_call, tc, agent, depth, allowed_tools): tc
                        for tc in tool_calls
                    }
                    results: dict[str, str] = {}
                    for future in concurrent.futures.as_completed(futures):
                        tc = futures[future]
                        try:
                            results[tc.id] = future.result()
                        except Exception as exc:
                            results[tc.id] = json.dumps({"error": f"Tool execution error: {exc}"})
                for tc in tool_calls:
                    last_tool = tc.function.name
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": results[tc.id]})

        usage = self._local.last_usage
        return (
            f"[Engine] Reached {MAX_TOOL_ITERATIONS} tool iterations "
            f"(last tool: {last_tool}, tokens in: {usage['in']}, out: {usage['out']}). "
            "Stopping."
        )

    # ── Session memory extraction ──────────────────────────────────

    def _extract_session_memory(
        self, agent: AgentDefinition, messages: list[dict]
    ) -> None:
        """End-of-session LLM call to extract durable facts."""
        if len(messages) < MEMORY_MIN_MESSAGES:
            return

        base_prompt = (
            "Review the conversation above and extract facts worth saving to persistent memory.\n\n"
            "SAVE:\n"
            "- User preferences and standing instructions (e.g. 'always CC finance@', 'use category X for travel')\n"
            "- Recurring patterns and corrected behaviors (e.g. vendor names, folder structures, naming conventions)\n"
            "- Stable identifiers the agent will need again (e.g. spreadsheet IDs, folder IDs, contact emails)\n"
            "- Decisions that should change future behavior\n\n"
            "DO NOT SAVE:\n"
            "- One-off task results (e.g. 'receipt #47 was processed', 'file X was uploaded today')\n"
            "- Anything derivable from the skill instructions or agent description\n"
            "- Session-specific details that won't apply next time\n\n"
        )
        if agent.memory_guidance:
            base_prompt += f"Additional guidance for this agent:\n{agent.memory_guidance}\n\n"
        extraction_prompt = (
            base_prompt
            + "Return ONLY a bullet list (one fact per line, starting with '- '). "
            "If nothing meets the bar above, return exactly: NOTHING"
        )

        extract_messages = messages + [{"role": "user", "content": extraction_prompt}]

        try:
            response = self._call_llm(extract_messages, tools=None)
            content = response.choices[0].message.content or ""
            content = content.strip()

            if content and content != "NOTHING":
                bulk_cap = MEMORY_WRITE_MAX_CHARS * 10
                if len(content) > bulk_cap:
                    content = content[:bulk_cap] + "\n... [truncated]"
                mem_path = agent.agent_dir / "memory.md"
                lock = self._get_mem_lock(mem_path)
                with lock:
                    with open(mem_path, "a", encoding="utf-8") as f:
                        f.write(f"\n{content}\n")
                    self._maybe_compress_memory(mem_path)
        except Exception:
            pass  # Don't crash on memory extraction failure

    # ── Public API ─────────────────────────────────────────────────

    def run_task(self, agent_slug: str, task: str, depth: int = 0, context: str = "") -> str:
        """Run a single task with the specified agent (non-interactive)."""
        agent = self.agents.get(agent_slug)
        if not agent:
            return f"[Error] Agent '{agent_slug}' not found."

        system_prompt = self._build_system_prompt(agent)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        if context:
            messages.append({"role": "user", "content": f"[Context from delegating agent]\n{context}"})
        messages.append({"role": "user", "content": task})

        result = self._completion_loop(agent, messages, depth)
        self._extract_session_memory(agent, messages)
        return result

    def run_interactive(self, agent_slug: str = "mini-me") -> None:
        """Interactive REPL loop with the specified agent."""
        agent = self.agents.get(agent_slug)
        if not agent:
            print(f"[Error] Agent '{agent_slug}' not found.")
            print(f"Available agents: {', '.join(self.agents.keys())}")
            return

        system_prompt = self._build_system_prompt(agent)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        print(f"🤖 {self._c(agent.name, self._BOLD, self._GREEN)} ready. (model: {self.model})")
        print("Type 'quit' or 'exit' to end the session.\n")

        user_prompt = self._c("● You: ", self._BOLD, self._CYAN)
        agent_label = self._c(f"● {agent.name}: ", self._BOLD, self._GREEN)

        # Store session state for crash handlers
        self._session_agent = agent
        self._session_messages = messages

        def _atexit_handler() -> None:
            if self._session_agent is not None:
                self._extract_session_memory(self._session_agent, self._session_messages)
                self._session_agent = None  # prevent double-extraction

        atexit.register(_atexit_handler)

        original_sigterm = signal.getsignal(signal.SIGTERM)

        def _sigterm_handler(signum, frame):
            print("\n[SIGTERM received — saving session memory...]")
            _atexit_handler()
            signal.signal(signal.SIGTERM, original_sigterm)
            signal.raise_signal(signal.SIGTERM)

        signal.signal(signal.SIGTERM, _sigterm_handler)

        try:
            while True:
                try:
                    user_input = input(user_prompt).strip()
                except EOFError:
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("quit", "exit"):
                    break

                messages.append({"role": "user", "content": user_input})
                try:
                    with self._spinner(agent.name):
                        response = self._completion_loop(agent, messages, depth=0)
                except Exception as e:
                    print(f"\n[Error] {e}. Session preserved — type another message.\n")
                    messages.pop()  # remove the failed user message
                    continue
                usage = getattr(self._local, "last_usage", {"in": 0, "out": 0})
                token_info = self._c(
                    f"↑{usage['in']} ↓{usage['out']}",
                    "\033[2m",  # dim
                )
                messages.append({"role": "assistant", "content": response})
                print(f"\n{agent_label}{response}\n{token_info}\n")

        except KeyboardInterrupt:
            print("\n")
        finally:
            print("Extracting session memory...")
            _atexit_handler()  # None-guard prevents double-run if atexit also fires
            print("Session ended.")
            signal.signal(signal.SIGTERM, original_sigterm)

    def list_agents(self) -> list[dict]:
        """Return summary of all loaded agents."""
        return [
            {
                "slug": a.slug,
                "name": a.name,
                "description": a.description,
                "tools": a.tools,
                "delegates_to": a.delegates_to,
                "skills": a.skills,
            }
            for a in self.agents.values()
        ]
