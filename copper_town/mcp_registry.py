"""MCPClientManager: lazy-connect MCP servers, execute tools, expose LiteLLM schemas."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import yaml

from .utils import interpolate_env

logger = logging.getLogger("copper_town.mcp")

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    logger.warning("mcp package not installed; MCP servers will be unavailable.")


class MCPClientManager:
    """Manages lazy connections to MCP servers and tool dispatch."""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._server_configs: dict[str, dict] = {}
        self._sessions: dict[str, Any] = {}          # server_slug → ClientSession
        self._tool_map: dict[str, str] = {}           # tool_name → server_slug
        self._schemas: dict[str, list[dict]] = {}     # server_slug → LiteLLM schemas
        self._connection_tasks: dict[str, asyncio.Task] = {}  # server_slug → owner task
        self._close_events: dict[str, asyncio.Event] = {}     # server_slug → close signal
        self._connect_locks: dict[str, asyncio.Lock] = {}
        self._load_config()

    def _load_config(self) -> None:
        if not self._config_path.exists():
            return
        with open(self._config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        servers = (data or {}).get("servers", {})
        for slug, cfg in servers.items():
            self._server_configs[slug] = cfg
            self._connect_locks[slug] = asyncio.Lock()

    @staticmethod
    def _tool_to_schema(tool: Any) -> dict:
        """Convert an MCP Tool to a LiteLLM-compatible schema."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema,
            },
        }

    async def ensure_connected(self, server_slug: str) -> None:
        """Lazily connect to an MCP server. Idempotent.

        Each connection runs in a dedicated asyncio Task that owns the AsyncExitStack,
        so the context managers are always entered and exited within the same task —
        avoiding anyio cancel-scope cross-task errors on close.
        """
        if not _MCP_AVAILABLE:
            raise RuntimeError("mcp package is not installed. Run: pip install mcp")
        if server_slug not in self._server_configs:
            raise ValueError(f"Unknown MCP server: {server_slug!r}")
        if server_slug in self._sessions:
            return
        lock = self._connect_locks[server_slug]
        async with lock:
            if server_slug in self._sessions:
                return
            cfg = self._server_configs[server_slug]
            transport = cfg.get("transport", "stdio")
            ready: asyncio.Event = asyncio.Event()
            close: asyncio.Event = asyncio.Event()
            error_box: list[Exception] = []

            async def _run_connection() -> None:
                stack = AsyncExitStack()
                try:
                    if transport == "stdio":
                        command: list[str] = cfg["command"]
                        if not command:
                            raise ValueError(f"MCP server has an empty command list in mcp.yml")
                        raw_env = cfg.get("env", {})
                        env = {k: interpolate_env(str(v), fallback_original=False) for k, v in raw_env.items()}
                        params = StdioServerParameters(
                            command=command[0],
                            args=command[1:],
                            env=env or None,
                        )
                        read, write = await stack.enter_async_context(stdio_client(params))
                    elif transport == "sse":
                        url: str = cfg["url"]
                        read, write = await stack.enter_async_context(sse_client(url))
                    else:
                        raise ValueError(f"Unsupported MCP transport: {transport!r}")

                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()

                    tools_result = await session.list_tools()
                    schemas = [self._tool_to_schema(t) for t in tools_result.tools]
                    for t in tools_result.tools:
                        if t.name in self._tool_map:
                            logger.warning(
                                "MCP tool '%s' from server '%s' shadows existing registration from '%s'.",
                                t.name, server_slug, self._tool_map[t.name],
                            )
                        self._tool_map[t.name] = server_slug
                    self._schemas[server_slug] = schemas
                    self._sessions[server_slug] = session
                    logger.info(
                        "MCP server '%s' connected: %d tools available.",
                        server_slug,
                        len(schemas),
                    )
                    ready.set()
                    await close.wait()
                except Exception as exc:
                    error_box.append(exc)
                    ready.set()
                finally:
                    await stack.aclose()
                    self._sessions.pop(server_slug, None)
                    self._schemas.pop(server_slug, None)
                    self._tool_map = {k: v for k, v in self._tool_map.items() if v != server_slug}

            conn_task = asyncio.create_task(_run_connection())
            await ready.wait()

            if error_box:
                await asyncio.gather(conn_task, return_exceptions=True)
                raise error_box[0]

            self._connection_tasks[server_slug] = conn_task
            self._close_events[server_slug] = close

    def servers_for_agent(self, agent_slug: str) -> list[str]:
        """Return server slugs assigned to *agent_slug* via ``agents`` in mcp.yml.

        A server matches if its ``agents`` list contains the slug or ``"*"``.
        Servers with no ``agents`` key are not auto-assigned.
        """
        result: list[str] = []
        for slug, cfg in self._server_configs.items():
            targets = cfg.get("agents", [])
            if agent_slug in targets or "*" in targets:
                result.append(slug)
        return result

    def get_schemas(self, server_names: list[str]) -> list[dict]:
        """Return cached schemas for already-connected servers."""
        result: list[dict] = []
        for slug in server_names:
            result.extend(self._schemas.get(slug, []))
        return result

    def server_for_tool(self, tool_name: str) -> str | None:
        """Return the server slug that owns this tool, or None."""
        return self._tool_map.get(tool_name)

    async def execute(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool on the appropriate MCP server."""
        server_slug = self._tool_map.get(tool_name)
        if server_slug is None:
            return json.dumps({"error": f"Unknown MCP tool: {tool_name!r}"})
        await self.ensure_connected(server_slug)
        session = self._sessions[server_slug]
        result = await session.call_tool(tool_name, arguments)
        if getattr(result, "isError", False):
            text = result.content[0].text if result.content and hasattr(result.content[0], "text") else "unknown error"
            return json.dumps({"error": text})
        if result.content:
            first = result.content[0]
            if hasattr(first, "text"):
                return first.text
            return json.dumps([c.model_dump() for c in result.content])
        return json.dumps({"success": True})

    async def close(self) -> None:
        """Close all MCP server connections.

        Signals each connection's dedicated task to shut down and waits for it.
        Safe to call from any asyncio task.
        """
        for close_event in self._close_events.values():
            close_event.set()
        tasks = list(self._connection_tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._connection_tasks.clear()
        self._close_events.clear()
        self._sessions.clear()
        self._tool_map.clear()
        self._schemas.clear()
