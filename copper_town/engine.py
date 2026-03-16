"""Core engine: async agent loading, tool dispatch, completion loop, delegation."""

from __future__ import annotations

import asyncio
import contextvars
import datetime
import itertools
import json
import logging
import re
import sys
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import aiofiles
import litellm

from .config import (
    AGENTS_DIR,
    BG_RESULT_MAX_CHARS,
    CONTEXT_SUMMARIZE,
    DELEGATION_RETRY_COUNT,
    GLOBAL_SKILLS_DIR,
    LOG_LEVEL,
    MAX_CONTEXT_MESSAGES,
    MAX_DELEGATION_DEPTH,
    MAX_SYSTEM_PROMPT_CHARS,
    MAX_TOOL_ITERATIONS,
    MAX_TOOL_OUTPUT_CHARS,
    MCP_CONFIG_PATH,
    MEMORY_COMPRESS_ENABLED,
    MEMORY_DB_PATH,
    MEMORY_MAX_LINES,
    MEMORY_MIN_MESSAGES,
    MEMORY_WRITE_MAX_CHARS,
    MODEL,
    SKILLS_DIR,
    validate_env,
)
from .background import BackgroundTaskManager
from .mcp_registry import MCPClientManager
from .events import Event, EventBus, EventType
from .memory_store import MemoryStore
from .utils import interpolate_env, parse_bullet_entries, parse_markdown_frontmatter
from .models import AgentResult, AgentStatus
from .tools import ToolRegistry

logger = logging.getLogger("copper_town")


# ── Streaming result types ──────────────────────────────────────────────────

@dataclass
class _StreamFn:
    name: str
    arguments: str


@dataclass
class _StreamToolCall:
    """Typed stand-in for LiteLLM tool-call objects used within streaming path."""
    id: str
    function: _StreamFn


@dataclass
class _LLMResult:
    """Structured return from _call_llm_stream; eliminates SimpleNamespace duck-typing."""
    text: str | None
    tool_calls: list[_StreamToolCall] | None
    usage: dict


# Context variables (asyncio-compatible replacements for threading.local)
# No mutable defaults — each call site passes a fresh fallback via .get()
_delegation_chain: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
    "delegation_chain",
)
_last_usage: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "last_usage",
)


def _record_usage(usage: object) -> None:
    """Accumulate prompt/completion token counts into the context-local usage dict."""
    current = _last_usage.get(None)
    if current is None:
        current = {"in": 0, "out": 0}
        _last_usage.set(current)
    current["in"] += getattr(usage, "prompt_tokens", 0)
    current["out"] += getattr(usage, "completion_tokens", 0)


@dataclass
class AgentDefinition:
    """Parsed agent from a .md file with YAML frontmatter."""

    slug: str
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    delegates_to: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    body: str = ""
    model: str | None = None
    memory_guidance: str = ""


class Engine:
    """LiteLLM-powered async agent engine with tool calling, delegation, and memory."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or MODEL
        validate_env(self.model)
        self.registry = ToolRegistry()
        self.agents: dict[str, AgentDefinition] = {}
        self.memory_store = MemoryStore(MEMORY_DB_PATH)
        self.event_bus = EventBus()
        self._initialized = False
        self._active_delegations: dict[str, int] = {}  # slug → count of running delegations
        self._delegation_display_lock = threading.Lock()
        self._bg = BackgroundTaskManager()
        self._manager = None  # set by enable_manager()
        # C3: only instantiate MCPClientManager when mcp.yml has servers defined
        import yaml as _yaml
        _mcp_cfg = {}
        if MCP_CONFIG_PATH.exists():
            with open(MCP_CONFIG_PATH, encoding="utf-8") as _f:
                _mcp_cfg = _yaml.safe_load(_f) or {}
        if _mcp_cfg.get("servers"):
            self.mcp_registry: MCPClientManager | None = MCPClientManager(MCP_CONFIG_PATH)
        else:
            self.mcp_registry = None
        logging.basicConfig(
            level=getattr(logging, LOG_LEVEL.upper(), logging.WARNING),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        self._load_all_agents()

    async def _ensure_initialized(self) -> None:
        """Initialize async resources on first use."""
        if not self._initialized:
            await self.memory_store.initialize()
            self._initialized = True

    async def close(self) -> None:
        """Clean up async resources."""
        await self.memory_store.close()
        if self.mcp_registry is not None:
            await self.mcp_registry.close()

    # ── Agent loading ──────────────────────────────────────────────

    def _load_all_agents(self) -> None:
        """Scan agents/*.md and parse frontmatter + body."""
        if not AGENTS_DIR.exists():
            return
        for path in sorted(AGENTS_DIR.glob("*.md")):
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
        front, body = parse_markdown_frontmatter(text)
        if not front:
            logger.debug("Skipping '%s': no YAML frontmatter found.", path.name)
            return None
        slug = path.stem
        return AgentDefinition(
            slug=slug,
            name=front.get("name", slug),
            description=front.get("description", ""),
            tools=front.get("tools", []),
            delegates_to=front.get("delegates_to", []),
            skills=front.get("skills", []),
            mcp_servers=front.get("mcp_servers", []),
            body=body,
            model=front.get("model"),
            memory_guidance=front.get("memory_guidance", ""),
        )

    # ── System prompt assembly ─────────────────────────────────────

    @staticmethod
    def _sanitize_memory(text: str) -> str:
        """Sanitize memory content before injecting into system prompts."""
        lines = text.splitlines()
        sanitized = []
        for line in lines:
            if re.match(r"^-{3,}\s*$", line):
                continue  # drop bare separator lines
            line = re.sub(r"^(#{1,6}\s)", r"[\1", line)
            if line.startswith("[#"):
                line = line + "]"
            sanitized.append(line)
        result = re.sub(r"\n{3,}", "\n\n", "\n".join(sanitized))
        return result

    async def _build_system_prompt(self, agent: AgentDefinition) -> str:
        """Assemble agent body + skills + memory into a system prompt."""
        now = datetime.datetime.now().strftime("%A, %B %-d, %Y %-I:%M %p")
        parts: list[str] = [f"Current date and time: {now}", interpolate_env(agent.body)]

        # Global skills
        if GLOBAL_SKILLS_DIR.exists():
            for skill_path in sorted(GLOBAL_SKILLS_DIR.glob("*.md")):
                async with aiofiles.open(skill_path, encoding="utf-8") as f:
                    content = (await f.read()).strip()
                if content:
                    content = interpolate_env(content)
                    parts.append(f"\n\n---\n## Skill: {skill_path.stem}\n\n{content}")

        # Agent-specific skills (search entire skills tree)
        for skill_name in agent.skills:
            matches = list(SKILLS_DIR.rglob(f"{skill_name}.md"))
            if not matches:
                logger.warning("Agent '%s' declares skill '%s' but no matching file found.", agent.slug, skill_name)
                continue
            skill_path = matches[0]
            async with aiofiles.open(skill_path, encoding="utf-8") as f:
                raw = (await f.read()).strip()
            # Strip frontmatter from skill
            m = re.match(r"^---\s*\n.*?\n---\s*\n(.*)", raw, re.DOTALL)
            content = m.group(1).strip() if m else raw
            content = interpolate_env(content)
            parts.append(f"\n\n---\n## Skill: {skill_name}\n\n{content}")

        # Memory from SQLite
        global_mem = await self.memory_store.get_memory_text("__global__", scope="global")
        if global_mem:
            mem = self._sanitize_memory(global_mem)
            if mem:
                parts.append(f"\n\n---\n## Memory (global)\n\n{mem}")

        agent_mem = await self.memory_store.get_memory_text(agent.slug, scope="agent")
        if agent_mem:
            mem = self._sanitize_memory(agent_mem)
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

    def _effective_mcp_servers(self, agent: AgentDefinition) -> list[str]:
        """Return deduplicated MCP servers for *agent* (frontmatter + mcp.yml assignments)."""
        from_config = self.mcp_registry.servers_for_agent(agent.slug) if self.mcp_registry else []
        seen: set[str] = set()
        result: list[str] = []
        for slug in [*agent.mcp_servers, *from_config]:
            if slug not in seen:
                seen.add(slug)
                result.append(slug)
        return result

    def _resolve_tools(
        self, agent: AgentDefinition, depth: int
    ) -> list[dict]:
        """Collect tool schemas for the agent."""
        tool_names = list(agent.tools)

        # Always-on tools
        for t in ("remember", "search_skills", "load_skill"):
            if t not in tool_names:
                tool_names.append(t)

        # Delegation tools if allowed and not at max depth
        include_delegation = agent.delegates_to and depth < MAX_DELEGATION_DEPTH
        if include_delegation and "delegate_to_agent" not in tool_names:
            tool_names.append("delegate_to_agent")
        if not include_delegation and "delegate_background" in tool_names:
            tool_names.remove("delegate_background")
        if "delegate_background" in tool_names and "cancel_background_task" not in tool_names:
            tool_names.append("cancel_background_task")

        schemas = self.registry.get_schemas(tool_names)

        # Append MCP schemas; MCP wins on name collisions with @tool functions
        mcp_servers = self._effective_mcp_servers(agent)
        if mcp_servers and self.mcp_registry is not None:
            mcp_schemas = self.mcp_registry.get_schemas(mcp_servers)
            if mcp_schemas:
                mcp_names = {s["function"]["name"] for s in mcp_schemas}
                schemas = [s for s in schemas if s["function"]["name"] not in mcp_names]
                schemas.extend(mcp_schemas)

        # Patch delegation tool descriptions with valid targets for this agent
        if include_delegation:
            valid_slugs = ", ".join(agent.delegates_to)
            patched: list[dict] = []
            for schema in schemas:
                fn_name = schema.get("function", {}).get("name")
                if fn_name == "delegate_to_agent":
                    schema = {**schema, "function": {**schema["function"], "description": (
                        f"Delegate a task to a sub-agent. "
                        f"Valid targets for this agent: {valid_slugs}"
                    )}}
                elif fn_name == "delegate_background":
                    schema = {**schema, "function": {**schema["function"], "description": (
                        f"Delegate a task to a sub-agent in the background (non-blocking). "
                        f"Valid targets for this agent: {valid_slugs}"
                    )}}
                patched.append(schema)
            schemas = patched

        return schemas

    # ── Hallucination detection ─────────────────────────────────────
    # Matches first-person delegation intent (e.g. "I'll delegate…", "dispatching your
    # task now…") but NOT explanatory mentions ("you can delegate", "delegation works by…").
    _HALLUCINATION_PATTERN = re.compile(
        r"(?:"
        r"I(?:'ll|'m| will| am| have| can)\s+(?:dispatch|delegat)\w*"  # "I'll delegate…"
        r"|(?:dispatch|delegat)\w*\s+(?:this|the|that|a|your|it)\s+(?:task|request|job|work)"  # "delegating your task"
        r"|(?:let me|going to|about to)\s+(?:dispatch|delegat)\w*"  # "let me delegate"
        r")",
        re.IGNORECASE,
    )
    _CORRECTION_MESSAGE = (
        "[Engine] You described delegating a task but did not call any tool. "
        "You MUST call delegate_background now to actually dispatch the task. "
        "Do not write text — call the tool immediately."
    )

    @staticmethod
    def _err(msg: str) -> str:
        return json.dumps({"error": msg})

    def _apply_hallucination_correction(
        self,
        messages: list[dict],
        content: str,
        allowed_tools: set[str],
        already_corrected: bool,
        agent_slug: str,
    ) -> bool:
        """Append correction messages if delegation was hallucinated.

        Returns True if a correction was injected (caller should ``continue`` the loop).
        """
        if already_corrected or "delegate_background" not in allowed_tools:
            return False
        if not self._detect_hallucinated_delegation(content, agent_slug):
            return False
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": self._CORRECTION_MESSAGE})
        return True

    # Long, structured responses are explanations, not hallucinated actions.
    _HALLUCINATION_MAX_LEN = 400

    def _detect_hallucinated_delegation(self, content: str, agent_slug: str) -> bool:
        if len(content) > self._HALLUCINATION_MAX_LEN:
            return False
        if self._HALLUCINATION_PATTERN.search(content):
            logger.warning(
                "Hallucinated delegation detected for agent '%s' — injecting correction",
                agent_slug,
            )
            return True
        return False

    @staticmethod
    def _invalidate_prompt_app() -> None:
        """Force prompt_toolkit to redraw (e.g. after a background task completes)."""
        try:
            from prompt_toolkit import get_app_or_none
            app = get_app_or_none()
            if app is not None:
                app.invalidate()
        except Exception:
            pass

    # ── Spinner (thread-based for UI, wrapped as asynccontextmanager) ──

    @asynccontextmanager
    async def _spinner(self, message: str = "Thinking"):
        """Display an animated spinner on stdout while an async block executes.

        Yields a callable that stops the spinner immediately (for use when the
        first streaming token arrives and we want to take over the terminal).
        """
        stop = threading.Event()

        def spin() -> None:
            frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            for frame in itertools.cycle(frames):
                if stop.is_set():
                    break
                with self._delegation_display_lock:
                    active = dict(self._active_delegations)
                if active:
                    parts = []
                    for slug, count in active.items():
                        name = self.agents[slug].name if slug in self.agents else slug
                        parts.append(name if count == 1 else f"{name} ×{count}")
                    display = f"{message} → " + ", ".join(parts)
                else:
                    display = message
                sys.stdout.write(f"\r{frame} {display}...")
                sys.stdout.flush()
                stop.wait(0.1)
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()

        t = threading.Thread(target=spin, daemon=True)
        t.start()

        def stop_spinner() -> None:
            stop.set()
            t.join()

        try:
            yield stop_spinner
        finally:
            stop.set()
            t.join()

    # ── LLM call ───────────────────────────────────────────────────

    async def _retry_litellm(self, coro_factory: Callable[[], Any]) -> Any:
        """Run *coro_factory()* up to 3 times with exponential backoff on transient errors."""
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                return await coro_factory()
            except (litellm.RateLimitError, litellm.APIConnectionError) as e:
                last_exc = e
                await asyncio.sleep(2 ** attempt)
        assert last_exc is not None
        raise last_exc

    async def _call_llm(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        model: str | None = None,
    ) -> Any:
        """Call LiteLLM async with optional tool definitions. Retries on transient errors."""
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        return await self._retry_litellm(lambda: litellm.acompletion(**kwargs))

    async def _call_llm_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        on_token: Callable[[str], None],
        model: str | None = None,
    ) -> _LLMResult:
        """Stream from LiteLLM, calling *on_token* for each text chunk.

        Returns a typed _LLMResult — either with .text (text response) or
        .tool_calls (tool-call response). Eliminates the SimpleNamespace
        duck-typing hack and the self._stream_response instance variable.
        """
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools

        stream = await self._retry_litellm(lambda: litellm.acompletion(**kwargs))
        tc_accum: dict[int, dict] = {}
        text_parts: list[str] = []
        accumulated_usage: dict = {"in": 0, "out": 0}

        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage:
                _record_usage(usage)
                accumulated_usage = {"in": getattr(usage, "prompt_tokens", 0),
                                     "out": getattr(usage, "completion_tokens", 0)}

            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tc_accum:
                        tc_accum[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc_delta.id:
                        tc_accum[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc_accum[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tc_accum[idx]["arguments"] += tc_delta.function.arguments
                continue
            if delta and delta.content:
                on_token(delta.content)
                text_parts.append(delta.content)

        if tc_accum:
            tool_calls = [
                _StreamToolCall(
                    id=tc_accum[idx]["id"],
                    function=_StreamFn(
                        name=tc_accum[idx]["name"],
                        arguments=tc_accum[idx]["arguments"],
                    ),
                )
                for idx in sorted(tc_accum)
            ]
            return _LLMResult(text=None, tool_calls=tool_calls, usage=accumulated_usage)

        text = "".join(text_parts) or None
        return _LLMResult(text=text, tool_calls=None, usage=accumulated_usage)

    # ── Tool execution ─────────────────────────────────────────────

    async def _execute_tool_call(
        self,
        tool_call: Any,
        agent: AgentDefinition,
        depth: int,
        allowed_tools: set[str] | None = None,
    ) -> str:
        """Dispatch a tool call to its handler."""
        name = tool_call.function.name

        if allowed_tools is not None and name not in allowed_tools:
            return self._err(f"Tool '{name}' is not authorized for agent '{agent.name}'.")

        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return self._err("Invalid JSON in tool arguments")

        # Intercept delegation and remember
        _tool_t0 = time.monotonic()
        _tool_error: str | None = None
        try:
            if name == "delegate_to_agent":
                result = await self._handle_delegation(args, agent, depth)
            elif name == "delegate_background":
                result = await self._handle_background_delegation(args, agent, depth)
            elif name == "cancel_background_task":
                result = await self._handle_cancel_background(args)
            elif name == "remember":
                result = await self._handle_remember(args, agent)
            elif self.mcp_registry is not None and self.mcp_registry.server_for_tool(name):
                result = await self.mcp_registry.execute(name, args)
            else:
                result = await self.registry.execute_async(name, args)
        except Exception as exc:
            _tool_error = str(exc)
            result = self._err(_tool_error)
        finally:
            _tool_latency_ms = (time.monotonic() - _tool_t0) * 1000

        logger.debug("Tool '%s' returned %d chars", name, len(result))

        if len(result) > MAX_TOOL_OUTPUT_CHARS:
            trimmed = len(result) - MAX_TOOL_OUTPUT_CHARS
            result = result[:MAX_TOOL_OUTPUT_CHARS] + f"... [truncated {trimmed} chars]"

        await self.event_bus.publish(Event(
            type=EventType.TOOL_CALL_COMPLETE,
            source=agent.slug,
            data={
                "agent": agent.slug,
                "tool": name,
                "args_preview": tool_call.function.arguments[:120],
                "result_preview": result[:120],
                "latency_ms": round(_tool_latency_ms, 1),
                "success": _tool_error is None,
                "error": _tool_error,
            },
        ))
        return result

    def _resolve_target_slug(self, raw_target: str, agent: AgentDefinition) -> str | None:
        """Resolve a delegation target to a slug, or return None if not allowed."""
        if raw_target in agent.delegates_to:
            return raw_target
        normalized = raw_target.lower().replace(" ", "-")
        via_name = self._name_to_slug.get(normalized)
        if via_name and via_name in agent.delegates_to:
            return via_name
        return None

    def _delegation_error(self, raw_target: str, agent: AgentDefinition) -> str:
        """Return an error JSON string for an invalid delegation target."""
        valid = ", ".join(
            f"{s} ({self.agents[s].name})" if s in self.agents else s
            for s in agent.delegates_to
        )
        return self._err(f"Agent '{agent.name}' cannot delegate to '{raw_target}'. Valid targets: {valid}")

    async def _handle_delegation(
        self, args: dict, agent: AgentDefinition, depth: int,
    ) -> str:
        """Validate and execute delegation to a sub-agent."""
        raw_target = args.get("agent", "")
        task = args.get("task", "")
        context = args.get("context", "")

        target_slug = self._resolve_target_slug(raw_target, agent)
        if target_slug is None:
            return self._delegation_error(raw_target, agent)

        if target_slug not in self.agents:
            return self._err(f"Agent '{target_slug}' not found.")

        if depth >= MAX_DELEGATION_DEPTH:
            return self._err("Maximum delegation depth reached.")

        # Use contextvars for delegation chain (create new list, don't mutate)
        chain = _delegation_chain.get([]) + [agent.slug]

        chain_str = " → ".join(chain + [target_slug])
        logger.info("Delegation start: %s (depth=%d, chain: %s)", target_slug, depth + 1, chain_str)
        with self._delegation_display_lock:
            self._active_delegations[target_slug] = self._active_delegations.get(target_slug, 0) + 1

        await self.event_bus.publish(Event(
            type=EventType.TASK_DELEGATED,
            source=agent.slug,
            data={"target": target_slug, "task": task, "depth": depth + 1},
        ))

        agent_result: Any = None
        try:
            for attempt in range(1 + DELEGATION_RETRY_COUNT):
                token = _delegation_chain.set(chain)
                try:
                    agent_result = await self.run_task(target_slug, task, depth=depth + 1, context=context)
                finally:
                    _delegation_chain.reset(token)
                if agent_result.succeeded:
                    break
                if attempt < DELEGATION_RETRY_COUNT:
                    logger.warning(
                        "Delegation to '%s' failed (attempt %d/%d), retrying...",
                        target_slug, attempt + 1, 1 + DELEGATION_RETRY_COUNT,
                    )
                    await asyncio.sleep(1)
        finally:
            with self._delegation_display_lock:
                count = self._active_delegations.get(target_slug, 0) - 1
                if count <= 0:
                    self._active_delegations.pop(target_slug, None)
                else:
                    self._active_delegations[target_slug] = count

        result_json = agent_result.to_tool_response()
        logger.info("Delegation end: %s, result size=%d chars", target_slug, len(result_json))
        return result_json

    async def _handle_background_delegation(
        self, args: dict, agent: AgentDefinition, depth: int
    ) -> str:
        """Start a delegated task in the background and return immediately with a task_id."""
        raw_target = args.get("agent", "")
        task = args.get("task", "")
        context = args.get("context", "")

        target_slug = self._resolve_target_slug(raw_target, agent)
        if target_slug is None:
            return self._delegation_error(raw_target, agent)

        if target_slug not in self.agents:
            return self._err(f"Agent '{target_slug}' not found.")
        if depth >= MAX_DELEGATION_DEPTH:
            return self._err("Maximum delegation depth reached.")

        task_id = self._bg.new_task_id(target_slug)
        confirmed_task = task if "confirmed" in task.lower() else f"{task} — confirmed, proceed."

        async def _bg_run() -> None:
            agent_name = self.agents[target_slug].name if target_slug in self.agents else target_slug
            try:
                result = await self.run_task(target_slug, confirmed_task, depth=depth + 1, context=context)
                if result.succeeded:
                    preview = result.result[:BG_RESULT_MAX_CHARS]
                    notification = (
                        f"[Background task completed]\n"
                        f"Agent: {agent_name} | Task ID: {task_id}\n"
                        f"Task: {task[:120]}\n"
                        f"Result:\n{preview}"
                    )
                else:
                    notification = (
                        f"[Background task failed]\n"
                        f"Agent: {agent_name} | Task ID: {task_id}\n"
                        f"Task: {task[:120]}\n"
                        f"Error: {result.error or 'unknown error'}"
                    )
            except Exception as exc:
                notification = (
                    f"[Background task error]\n"
                    f"Agent: {agent_name} | Task ID: {task_id}\n"
                    f"Task: {task[:120]}\n"
                    f"Error: {exc}"
                )
            finally:
                self._bg.complete(task_id)
                self._invalidate_prompt_app()

            self._bg.add_notification(notification)

        bg_task = asyncio.create_task(_bg_run())
        self._bg.register(task_id, target_slug, task, bg_task)

        await self.event_bus.publish(Event(
            type=EventType.TASK_BACKGROUND_STARTED,
            source=agent.slug,
            data={"target": target_slug, "task": task, "depth": depth + 1, "task_id": task_id},
        ))

        return json.dumps({
            "status": "started",
            "task_id": task_id,
            "agent": target_slug,
            "message": f"Task dispatched to {self.agents[target_slug].name} in the background. Result delivered next turn.",
        })

    async def _handle_cancel_background(self, args: dict) -> str:
        """Cancel a running background task by task_id."""
        task_id = args.get("task_id", "")
        meta = self._bg.get_meta(task_id)
        status = self._bg.cancel(task_id)

        if status == "not_found":
            return self._err(f"No active task with id '{task_id}'. It may have already completed or never existed.")
        if status == "already_completed":
            return json.dumps({"status": "already_completed", "task_id": task_id})

        await self.event_bus.publish(Event(
            type=EventType.TASK_CANCELLED,
            source="engine",
            data={"task_id": task_id, "agent": meta.get("agent", "unknown")},
        ))
        self._invalidate_prompt_app()
        return json.dumps({"status": "cancelled", "task_id": task_id})

    async def _handle_remember(self, args: dict, agent: AgentDefinition) -> str:
        """Add content to the memory store."""
        content = args.get("content", "").strip()
        scope = args.get("scope", "agent")
        pin = bool(args.get("pin", False))

        if not content:
            return self._err("No content provided to remember.")

        # Collapse multi-line content to a single line (prevents header injection)
        content = " ".join(content.splitlines())
        # Enforce size cap
        if len(content) > MEMORY_WRITE_MAX_CHARS:
            content = content[:MEMORY_WRITE_MAX_CHARS] + "... [truncated]"

        agent_slug = "__global__" if scope == "global" else agent.slug
        await self.memory_store.add(agent_slug, content, scope=scope, pin=pin)

        await self.event_bus.publish(Event(
            type=EventType.MEMORY_UPDATED,
            source=agent.slug,
            data={"scope": scope, "content": content[:100]},
        ))

        await self._maybe_compress_memory(agent_slug, scope)

        current_memory = await self.memory_store.get_memory_text(agent_slug, scope=scope)

        logger.debug("Memory write: agent='%s', scope='%s'", agent.slug, scope)
        return json.dumps({
            "saved": True,
            "scope": scope,
            "current_memory": current_memory,
        })

    # ── Memory compression ─────────────────────────────────────────

    async def _maybe_compress_memory(self, agent_slug: str, scope: str) -> None:
        """If memory exceeds MEMORY_MAX_LINES, deduplicate unpinned entries via LLM."""
        count = await self.memory_store.count_entries(agent_slug, scope=scope)
        if count <= MEMORY_MAX_LINES:
            return
        if not MEMORY_COMPRESS_ENABLED:
            logger.debug("Memory compression disabled (MEMORY_COMPRESS_ENABLED=false); skipping.")
            return

        unpinned = await self.memory_store.get_memories(agent_slug, scope=scope, pinned=False)
        if not unpinned:
            return  # All entries are pinned; nothing to compress

        logger.warning(
            "Compressing memory for agent='%s', scope='%s' (%d entries, %d unpinned). "
            "Contents will be sent to the LLM provider for deduplication. "
            "Set MEMORY_COMPRESS_ENABLED=false to disable.",
            agent_slug, scope, count, len(unpinned),
        )
        unpinned_text = "\n".join(f"- {e.content}" for e in unpinned)
        prompt = (
            "The following is a memory file with accumulated facts. "
            "Deduplicate, remove contradictions, and consolidate into a clean bullet list. "
            "Keep all unique facts. Return ONLY the bullet list.\n\n"
            + unpinned_text
        )
        try:
            response = await self._call_llm(
                [{"role": "user", "content": prompt}], tools=None
            )
            compressed = response.choices[0].message.content.strip()
            compressed_entries = parse_bullet_entries(compressed)
            if compressed_entries:
                # replace_memories preserves pinned entries automatically
                await self.memory_store.replace_memories(agent_slug, scope, compressed_entries)
        except Exception as exc:
            logger.warning("Memory compression failed for agent='%s', scope='%s': %s", agent_slug, scope, exc)

    async def _summarize_messages(self, to_trim: list[dict]) -> str | None:
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
            response = await self._call_llm([{"role": "user", "content": prompt}], tools=None)
            return response.choices[0].message.content.strip() or None
        except Exception:
            logger.debug("Context summarization failed; using generic notice.")
            return None

    async def _trim_context_window(self, messages: list[dict], agent_slug: str) -> None:
        """Trim messages in-place when context exceeds MAX_CONTEXT_MESSAGES."""
        if len(messages) <= MAX_CONTEXT_MESSAGES + 1:
            return

        keep_from = max(1, len(messages) - MAX_CONTEXT_MESSAGES)
        # Back up to avoid orphaning tool-result messages from their assistant
        while keep_from > 1 and messages[keep_from].get("role") == "tool":
            keep_from -= 1

        # If we backed up all the way, force a trim anyway to prevent unbounded growth
        if keep_from <= 1:
            keep_from = max(2, len(messages) - MAX_CONTEXT_MESSAGES)

        to_trim = messages[1:keep_from]
        keep_tail = messages[keep_from:]
        summary = await self._summarize_messages(to_trim)
        notice_text = (
            f"[Earlier context summarized: {summary}]" if summary
            else "[Earlier context trimmed to stay within limits.]"
        )
        # Mutate in-place so the caller's reference stays in sync
        messages[:] = [messages[0], {"role": "system", "content": notice_text}] + keep_tail
        logger.warning("Context trimmed for agent '%s': evicted %d messages.", agent_slug, len(to_trim))

    # ── Completion-loop helpers ────────────────────────────────────

    async def _emit_llm_complete(
        self,
        agent_slug: str,
        model: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        tool_calls_count: int,
        latency_ms: float,
        iteration: int,
    ) -> None:
        await self.event_bus.publish(Event(
            type=EventType.LLM_CALL_COMPLETE,
            source=agent_slug,
            data={
                "agent": agent_slug,
                "model": model or self.model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "tool_calls_count": tool_calls_count,
                "latency_ms": round(latency_ms, 1),
                "iteration": iteration,
            },
        ))

    async def _execute_and_append_tool_results(
        self,
        tool_calls: list,
        messages: list[dict],
        agent: "AgentDefinition",
        depth: int,
        allowed_tools: set[str],
    ) -> str:
        """Execute tool calls (parallel if multiple), append results, return last tool name."""
        if len(tool_calls) == 1:
            tc = tool_calls[0]
            res = await self._execute_tool_call(tc, agent, depth, allowed_tools)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": res})
            return tc.function.name
        results = await asyncio.gather(
            *(self._execute_tool_call(tc, agent, depth, allowed_tools) for tc in tool_calls)
        )
        last = ""
        for tc, res in zip(tool_calls, results):
            last = tc.function.name
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": res})
        return last

    # ── Completion loop ────────────────────────────────────────────

    async def _completion_loop(
        self,
        agent: AgentDefinition,
        messages: list[dict],
        depth: int,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Call LLM → handle tool calls → loop until text response or safety cap.

        If on_token is provided, the final text response is streamed chunk-by-chunk
        via on_token(chunk). Tool-call iterations are always buffered silently.
        """
        # Lazily connect any declared MCP servers before resolving tool schemas
        mcp_servers = self._effective_mcp_servers(agent)
        if mcp_servers and self.mcp_registry is not None:
            await asyncio.gather(
                *[self.mcp_registry.ensure_connected(s) for s in mcp_servers]
            )

        tools = self._resolve_tools(agent, depth)
        allowed_tools: set[str] = {
            s["function"]["name"] for s in tools
        }
        _last_usage.set({"in": 0, "out": 0})

        last_tool: str | None = None
        # Hallucination correction: track whether we've already injected a correction
        # this loop so we don't loop infinitely.
        _hallucination_corrected = False
        # Local alias so we can suppress streaming after a hallucination is detected
        # (correction turn should not stream — the streamed text is already shown).
        _use_on_token = on_token

        for _iter in range(MAX_TOOL_ITERATIONS):
            await self._trim_context_window(messages, agent.slug)

            _llm_t0 = time.monotonic()

            # Streaming path: on_token is called per chunk; _LLMResult carries the outcome.
            if _use_on_token is not None:
                stream_result = await self._call_llm_stream(
                    messages, tools or None, on_token=_use_on_token, model=agent.model
                )
                _llm_latency_ms = (time.monotonic() - _llm_t0) * 1000

                if stream_result.text is not None:
                    # Pure text response — no tool calls
                    content = stream_result.text
                    usage = _last_usage.get({"in": 0, "out": 0})
                    await self._emit_llm_complete(
                        agent.slug, agent.model, usage["in"], usage["out"],
                        0, _llm_latency_ms, _iter,
                    )
                    if self._apply_hallucination_correction(
                        messages, content, allowed_tools, _hallucination_corrected, agent.slug
                    ):
                        _hallucination_corrected = True
                        _use_on_token = None  # suppress streaming for correction turn
                        continue
                    return content

                if stream_result.tool_calls is not None:
                    # Tool-call response from stream
                    usage = _last_usage.get({"in": 0, "out": 0})
                    await self._emit_llm_complete(
                        agent.slug, agent.model, usage["in"], usage["out"],
                        len(stream_result.tool_calls), _llm_latency_ms, _iter,
                    )
                    tool_calls = stream_result.tool_calls
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    })
                    last_tool = await self._execute_and_append_tool_results(
                        tool_calls, messages, agent, depth, allowed_tools
                    )
                    continue

                # Stream yielded neither text nor tool calls — fall back to non-streaming
                _llm_t0 = time.monotonic()

            response = await self._call_llm(messages, tools or None, model=agent.model)

            _llm_latency_ms = (time.monotonic() - _llm_t0) * 1000
            usage = getattr(response, "usage", None)
            _prompt_tokens, _completion_tokens = 0, 0
            if usage:
                _prompt_tokens = getattr(usage, "prompt_tokens", 0)
                _completion_tokens = getattr(usage, "completion_tokens", 0)
                _record_usage(usage)
            choice = response.choices[0]
            message = choice.message

            await self._emit_llm_complete(
                agent.slug, agent.model, _prompt_tokens, _completion_tokens,
                len(message.tool_calls) if message.tool_calls else 0,
                _llm_latency_ms, _iter,
            )

            # If no tool calls, return text content
            if not message.tool_calls:
                content = message.content or ""
                # Some Ollama models return "{}" as a no-op placeholder instead of real text.
                # Treat it as empty so the loop can retry or the caller handles it gracefully.
                if content.strip() in ("{}", "null", "[]"):
                    content = ""
                if self._apply_hallucination_correction(
                    messages, content, allowed_tools, _hallucination_corrected, agent.slug
                ):
                    _hallucination_corrected = True
                    continue
                return content

            # Append assistant message with tool calls.
            # Exclude None fields — Ollama rejects messages with null tool_calls on follow-up turns.
            messages.append({k: v for k, v in message.model_dump().items() if v is not None})

            last_tool = await self._execute_and_append_tool_results(
                message.tool_calls, messages, agent, depth, allowed_tools
            )

        usage = _last_usage.get({"in": 0, "out": 0})
        return (
            f"[Engine] Reached {MAX_TOOL_ITERATIONS} tool iterations "
            f"(last tool: {last_tool}, tokens in: {usage['in']}, out: {usage['out']}). "
            "Stopping."
        )

    # ── Session memory extraction ──────────────────────────────────

    async def _extract_session_memory(
        self, agent: AgentDefinition, messages: list[dict]
    ) -> None:
        """End-of-session LLM call to extract durable facts."""
        if len(messages) < MEMORY_MIN_MESSAGES:
            return

        existing_memory = await self.memory_store.get_memory_text(agent.slug, scope="agent")

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
        if existing_memory:
            base_prompt += (
                "Already stored in memory (do not re-add facts already covered here; "
                "supersede outdated entries by including an updated version):\n"
                + existing_memory
                + "\n\n"
            )
        if agent.memory_guidance:
            base_prompt += f"Additional guidance for this agent:\n{agent.memory_guidance}\n\n"
        extraction_prompt = (
            base_prompt
            + "Return ONLY new or updated facts as a bullet list (one fact per line, starting with '- '). "
            "If nothing new meets the bar above, return exactly: NOTHING"
        )

        extract_messages = messages + [{"role": "user", "content": extraction_prompt}]

        try:
            response = await self._call_llm(extract_messages, tools=None)
            content = response.choices[0].message.content or ""
            content = content.strip()

            if content and content != "NOTHING":
                bulk_cap = MEMORY_WRITE_MAX_CHARS * 10
                if len(content) > bulk_cap:
                    content = content[:bulk_cap] + "\n... [truncated]"
                entries = parse_bullet_entries(content)
                if entries:
                    await self.memory_store.add_bulk(agent.slug, entries, scope="agent")
                    await self._maybe_compress_memory(agent.slug, "agent")
        except Exception as exc:
            logger.warning("Session memory extraction failed for agent='%s': %s", agent.slug, exc)

    # ── Public API ─────────────────────────────────────────────────

    async def run_task(
        self, agent_slug: str, task: str, depth: int = 0, context: str = ""
    ) -> AgentResult:
        """Run a single task with the specified agent (non-interactive). Returns AgentResult."""
        await self._ensure_initialized()

        agent = self.agents.get(agent_slug)
        if not agent:
            return AgentResult(
                status=AgentStatus.ERROR,
                result="",
                error=f"Agent '{agent_slug}' not found.",
                agent_slug=agent_slug,
                task=task,
            )

        await self.event_bus.publish(Event(
            type=EventType.AGENT_STARTED,
            source=agent_slug,
            data={"task": task, "depth": depth},
        ))

        try:
            system_prompt = await self._build_system_prompt(agent)
            messages: list[dict] = [{"role": "system", "content": system_prompt}]
            if context:
                messages.append({"role": "user", "content": f"[Context from delegating agent]\n{context}"})
            messages.append({"role": "user", "content": task})

            result_text = await self._completion_loop(agent, messages, depth)
            await self._extract_session_memory(agent, messages)

            agent_result = AgentResult(
                status=AgentStatus.SUCCESS,
                result=result_text,
                agent_slug=agent_slug,
                task=task,
            )
        except Exception as e:
            agent_result = AgentResult(
                status=AgentStatus.ERROR,
                result="",
                error=str(e),
                agent_slug=agent_slug,
                task=task,
            )

        event_type = EventType.AGENT_COMPLETED if agent_result.succeeded else EventType.AGENT_FAILED
        await self.event_bus.publish(Event(
            type=event_type,
            source=agent_slug,
            data={"status": agent_result.status.value, "task": task},
        ))

        return agent_result

    async def run_interactive(self, agent_slug: str = "mini-me") -> None:
        """Interactive REPL loop with the specified agent."""
        await self._ensure_initialized()
        from .repl import REPLSession
        await REPLSession(self, agent_slug).run()

    def enable_manager(
        self, max_concurrent: int = 10, default_timeout: float = 300.0
    ) -> "AgentManager":
        """Create and return an AgentManager for concurrent agent runs."""
        from .manager import AgentManager
        self._manager = AgentManager(
            engine=self,
            event_bus=self.event_bus,
            max_concurrent=max_concurrent,
            default_timeout=default_timeout,
        )
        return self._manager

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
