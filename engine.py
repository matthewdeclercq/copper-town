"""Core engine: async agent loading, tool dispatch, completion loop, delegation."""

from __future__ import annotations

import asyncio
import contextvars
import itertools
import json
import logging
import os
import re
import readline
import sys
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable

import aiofiles
import litellm
import yaml

from config import (
    AGENTS_DIR,
    CONTEXT_SUMMARIZE,
    DELEGATION_RETRY_COUNT,
    GLOBAL_SKILLS_DIR,
    LOG_LEVEL,
    MAX_CONTEXT_MESSAGES,
    MAX_DELEGATION_DEPTH,
    MAX_SYSTEM_PROMPT_CHARS,
    MAX_TOOL_ITERATIONS,
    MAX_TOOL_OUTPUT_CHARS,
    MEMORY_COMPRESS_ENABLED,
    MEMORY_DB_PATH,
    MEMORY_MAX_LINES,
    MEMORY_MIN_MESSAGES,
    MEMORY_WRITE_MAX_CHARS,
    MODEL,
    SKILLS_DIR,
    validate_env,
)
from events import Event, EventBus, EventType
from memory_store import MemoryStore, parse_bullet_entries
from models import AgentResult, AgentStatus
from tools import ToolRegistry

logger = logging.getLogger("copper_town")

# Context variables (asyncio-compatible replacements for threading.local)
_delegation_chain: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
    "delegation_chain", default=[]
)
_last_usage: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "last_usage", default={"in": 0, "out": 0}
)


@dataclass
class AgentDefinition:
    """Parsed agent from a .md file with YAML frontmatter."""

    slug: str
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    delegates_to: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
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
        self._spinner_status: list[str] = [""]  # mutable; updated live during delegation
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
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not match:
            return None
        front = yaml.safe_load(match.group(1)) or {}
        body = match.group(2).strip()
        slug = path.stem
        return AgentDefinition(
            slug=slug,
            name=front.get("name", slug),
            description=front.get("description", ""),
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

    @staticmethod
    def _interpolate_env(text: str) -> str:
        """Replace ${VAR_NAME} placeholders with environment variable values."""
        return re.sub(
            r"\$\{(\w+)\}",
            lambda m: os.getenv(m.group(1), m.group(0)),
            text,
        )

    async def _build_system_prompt(self, agent: AgentDefinition) -> str:
        """Assemble agent body + skills + memory into a system prompt."""
        parts: list[str] = [self._interpolate_env(agent.body)]

        # Global skills
        if GLOBAL_SKILLS_DIR.exists():
            for skill_path in sorted(GLOBAL_SKILLS_DIR.glob("*.md")):
                async with aiofiles.open(skill_path, encoding="utf-8") as f:
                    content = (await f.read()).strip()
                if content:
                    content = self._interpolate_env(content)
                    parts.append(f"\n\n---\n## Skill: {skill_path.stem}\n\n{content}")

        # Agent-specific skills (search entire skills tree)
        for skill_name in agent.skills:
            matches = list(SKILLS_DIR.rglob(f"{skill_name}.md"))
            skill_path = matches[0] if matches else None
            if skill_path:
                async with aiofiles.open(skill_path, encoding="utf-8") as f:
                    raw = (await f.read()).strip()
                # Strip frontmatter from skill
                m = re.match(r"^---\s*\n.*?\n---\s*\n(.*)", raw, re.DOTALL)
                content = m.group(1).strip() if m else raw
                content = self._interpolate_env(content)
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

    @staticmethod
    def _c_prompt(text: str, *codes: str) -> str:
        """Color a string for use in an input() prompt (readline-safe).

        Wraps escape sequences in \\x01/\\x02 so readline correctly computes
        the visible prompt length and cursor position.
        """
        esc = "".join(codes)
        return f"\x01{esc}\x02{text}\x01{Engine._RESET}\x02"

    # ── Spinner (thread-based for UI, wrapped as asynccontextmanager) ──

    @asynccontextmanager
    async def _spinner(self, message: str = "Thinking"):
        """Display an animated spinner on stdout while an async block executes.

        Yields a callable that stops the spinner immediately (for use when the
        first streaming token arrives and we want to take over the terminal).
        """
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

        def stop_spinner() -> None:
            stop.set()
            t.join()

        try:
            yield stop_spinner
        finally:
            stop.set()
            t.join()

    # ── LLM call ───────────────────────────────────────────────────

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

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                return await litellm.acompletion(**kwargs)
            except (litellm.RateLimitError, litellm.APIConnectionError) as e:
                last_exc = e
                await asyncio.sleep(2 ** attempt)
        raise last_exc  # type: ignore[misc]

    async def _call_llm_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream text chunks from LiteLLM. Yields nothing if response has tool calls.
        Updates _last_usage with token counts from the final chunk when available."""
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                stream = await litellm.acompletion(**kwargs)
                async for chunk in stream:
                    # Capture usage from any chunk that includes it (typically the last)
                    usage = getattr(chunk, "usage", None)
                    if usage:
                        current = _last_usage.get()
                        current["in"] += getattr(usage, "prompt_tokens", 0)
                        current["out"] += getattr(usage, "completion_tokens", 0)

                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.tool_calls:
                        # Tool-call response: drain remaining chunks silently and stop
                        async for remaining in stream:
                            remaining_usage = getattr(remaining, "usage", None)
                            if remaining_usage:
                                current = _last_usage.get()
                                current["in"] += getattr(remaining_usage, "prompt_tokens", 0)
                                current["out"] += getattr(remaining_usage, "completion_tokens", 0)
                        return
                    if delta and delta.content:
                        yield delta.content
                return
            except (litellm.RateLimitError, litellm.APIConnectionError) as e:
                last_exc = e
                await asyncio.sleep(2 ** attempt)
        if last_exc:
            raise last_exc

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
            return json.dumps({"error": f"Tool '{name}' is not authorized for agent '{agent.name}'."})

        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in tool arguments"})

        # Intercept delegation and remember
        _tool_t0 = time.monotonic()
        _tool_error: str | None = None
        try:
            if name == "delegate_to_agent":
                result = await self._handle_delegation(args, agent, depth)
            elif name == "remember":
                result = await self._handle_remember(args, agent)
            else:
                result = await self.registry.execute_async(name, args)
        except Exception as exc:
            _tool_error = str(exc)
            result = json.dumps({"error": _tool_error})
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

    async def _handle_delegation(
        self, args: dict, agent: AgentDefinition, depth: int,
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

        # Use contextvars for delegation chain (create new list, don't mutate)
        chain = _delegation_chain.get([])
        chain = chain + [agent.slug]

        chain_str = " → ".join(chain + [target_slug])
        logger.info("Delegation start: %s (depth=%d, chain: %s)", target_slug, depth + 1, chain_str)
        self._spinner_status[0] = chain_str

        await self.event_bus.publish(Event(
            type=EventType.TASK_DELEGATED,
            source=agent.slug,
            data={"target": target_slug, "task": task, "depth": depth + 1},
        ))

        agent_result: Any = None
        for attempt in range(1 + DELEGATION_RETRY_COUNT):
            token = _delegation_chain.set(chain)
            try:
                agent_result = await self.run_task(target_slug, task, depth=depth + 1, context=context)
            finally:
                _delegation_chain.reset(token)
                self._spinner_status[0] = agent.name
            if agent_result.succeeded:
                break
            if attempt < DELEGATION_RETRY_COUNT:
                logger.warning(
                    "Delegation to '%s' failed (attempt %d/%d), retrying...",
                    target_slug, attempt + 1, 1 + DELEGATION_RETRY_COUNT,
                )
                self._spinner_status[0] = chain_str
                await asyncio.sleep(1)

        result_json = agent_result.to_tool_response()
        logger.info("Delegation end: %s, result size=%d chars", target_slug, len(result_json))
        return result_json

    async def _handle_remember(self, args: dict, agent: AgentDefinition) -> str:
        """Add content to the memory store."""
        content = args.get("content", "").strip()
        scope = args.get("scope", "agent")
        pin = bool(args.get("pin", False))

        if not content:
            return json.dumps({"error": "No content provided to remember."})

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

        entries = await self.memory_store.get_memories(agent_slug, scope=scope)
        unpinned = [e for e in entries if not e.pinned]
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
        except Exception:
            pass  # Don't crash if compression fails

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
        tools = self._resolve_tools(agent, depth)
        allowed_tools: set[str] = {
            s["function"]["name"] for s in tools
        }
        _last_usage.set({"in": 0, "out": 0})

        last_tool: str | None = None

        for _iter in range(MAX_TOOL_ITERATIONS):
            # Sliding context window with optional summarization
            if len(messages) > MAX_CONTEXT_MESSAGES + 1:
                keep_from = max(1, len(messages) - MAX_CONTEXT_MESSAGES)
                while keep_from > 1 and messages[keep_from].get("role") == "tool":
                    keep_from -= 1

                to_trim = messages[1:keep_from]
                keep_tail = messages[keep_from:]
                summary = await self._summarize_messages(to_trim)
                notice_text = (
                    f"[Earlier context summarized: {summary}]" if summary
                    else "[Earlier context trimmed to stay within limits.]"
                )
                # Mutate in-place so the caller's reference stays in sync
                messages[:] = [messages[0], {"role": "system", "content": notice_text}] + keep_tail
                logger.warning("Context trimmed for agent '%s': evicted %d messages.", agent.slug, len(to_trim))

            _llm_t0 = time.monotonic()

            # Streaming path: only for the final text response (when on_token provided)
            # We try streaming first; if the response has tool calls the generator yields
            # nothing, so we fall through to the normal non-streaming path for tool dispatch.
            if on_token is not None:
                accumulated_chunks: list[str] = []
                has_content = False
                async for chunk in self._call_llm_stream(messages, tools or None, model=agent.model):
                    on_token(chunk)
                    accumulated_chunks.append(chunk)
                    has_content = True

                _llm_latency_ms = (time.monotonic() - _llm_t0) * 1000

                if has_content:
                    # Pure text response — no tool calls
                    content = "".join(accumulated_chunks)
                    usage = _last_usage.get()
                    await self.event_bus.publish(Event(
                        type=EventType.LLM_CALL_COMPLETE,
                        source=agent.slug,
                        data={
                            "agent": agent.slug,
                            "model": agent.model or self.model,
                            "prompt_tokens": usage["in"],
                            "completion_tokens": usage["out"],
                            "tool_calls_count": 0,
                            "latency_ms": round(_llm_latency_ms, 1),
                            "iteration": _iter,
                        },
                    ))
                    return content

                # No chunks = tool-call response; fall through to non-streaming dispatch
                # Reset timer for the non-streaming call below
                _llm_t0 = time.monotonic()

            response = await self._call_llm(messages, tools or None, model=agent.model)
            _llm_latency_ms = (time.monotonic() - _llm_t0) * 1000
            usage = getattr(response, "usage", None)
            _prompt_tokens, _completion_tokens = 0, 0
            if usage:
                current = _last_usage.get()
                _prompt_tokens = getattr(usage, "prompt_tokens", 0)
                _completion_tokens = getattr(usage, "completion_tokens", 0)
                current["in"] += _prompt_tokens
                current["out"] += _completion_tokens
            choice = response.choices[0]
            message = choice.message

            await self.event_bus.publish(Event(
                type=EventType.LLM_CALL_COMPLETE,
                source=agent.slug,
                data={
                    "agent": agent.slug,
                    "model": agent.model or self.model,
                    "prompt_tokens": _prompt_tokens,
                    "completion_tokens": _completion_tokens,
                    "tool_calls_count": len(message.tool_calls) if message.tool_calls else 0,
                    "latency_ms": round(_llm_latency_ms, 1),
                    "iteration": _iter,
                },
            ))

            # If no tool calls, return text content
            if not message.tool_calls:
                content = message.content or ""
                # Some Ollama models return "{}" as a no-op placeholder instead of real text.
                # Treat it as empty so the loop can retry or the caller handles it gracefully.
                if content.strip() in ("{}", "null", "[]"):
                    content = ""
                return content

            # Append assistant message with tool calls.
            # Exclude None fields — Ollama rejects messages with null tool_calls on follow-up turns.
            messages.append({k: v for k, v in message.model_dump().items() if v is not None})

            # Execute tool calls (parallel via asyncio.gather if multiple)
            tool_calls = message.tool_calls
            if len(tool_calls) == 1:
                tc = tool_calls[0]
                last_tool = tc.function.name
                result = await self._execute_tool_call(tc, agent, depth, allowed_tools)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            else:
                results = await asyncio.gather(
                    *(self._execute_tool_call(tc, agent, depth, allowed_tools) for tc in tool_calls)
                )
                for tc, result in zip(tool_calls, results):
                    last_tool = tc.function.name
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        usage = _last_usage.get()
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
        except Exception:
            pass  # Don't crash on memory extraction failure

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

            usage = _last_usage.get({"in": 0, "out": 0})
            agent_result = AgentResult(
                status=AgentStatus.SUCCESS,
                result=result_text,
                agent_slug=agent_slug,
                task=task,
                metadata={"token_usage": usage},
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
        from rich.console import Console
        from rich.markdown import Markdown

        await self._ensure_initialized()

        agent = self.agents.get(agent_slug)
        if not agent:
            print(f"[Error] Agent '{agent_slug}' not found.")
            print(f"Available agents: {', '.join(self.agents.keys())}")
            return

        system_prompt = await self._build_system_prompt(agent)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        console = Console()
        console.print(f"🤖 [bold green]{agent.name}[/bold green] ready. (model: {self.model})")
        console.print("Type 'quit' or 'exit' to end the session.\n")

        user_prompt = self._c_prompt("● You: ", self._BOLD, self._CYAN)
        agent_label = self._c(f"● {agent.name}: ", self._BOLD, self._GREEN)

        # readline history persistence
        _HISTORY_FILE = Path.home() / ".copper_history"
        try:
            readline.read_history_file(str(_HISTORY_FILE))
        except FileNotFoundError:
            pass
        readline.set_history_length(500)

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
                    async with self._spinner(agent.name) as stop_fn:
                        response = await self._completion_loop(
                            agent, messages, depth=0, on_token=on_token
                        )
                except Exception as e:
                    print(f"\n[Error] {e}. Session preserved — type another message.\n")
                    messages.pop()
                    continue

                elapsed = time.monotonic() - t0
                final_text = accumulated or response

                print(f"\n{agent_label}")
                if final_text:
                    console.print(Markdown(final_text))

                usage = _last_usage.get({"in": 0, "out": 0})
                token_info = self._c(
                    f"↑{usage['in']} ↓{usage['out']}  {elapsed:.1f}s",
                    "\033[2m",  # dim
                )
                messages.append({"role": "assistant", "content": response})
                print(f"{token_info}\n")

        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n")
        finally:
            readline.write_history_file(str(_HISTORY_FILE))
            async with self._spinner("Saving memory") as _stop:
                await self._extract_session_memory(agent, messages)
            await self.close()
            print("Session ended.")

    def enable_manager(
        self, max_concurrent: int = 10, default_timeout: float = 300.0
    ) -> "AgentManager":
        """Create and return an AgentManager for concurrent agent runs."""
        from manager import AgentManager
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
