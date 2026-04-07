"""Tool framework: @tool decorator and ToolRegistry."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import pkgutil
import typing
from pathlib import Path
from typing import Any, Callable, get_type_hints


def _python_type_to_json_schema(t: type) -> dict:
    """Convert a Python type annotation to a JSON Schema type."""
    origin = getattr(t, "__origin__", None)
    args = getattr(t, "__args__", ())

    # Optional[X] / Union[X, None]
    if origin is typing.Union and type(None) in args:
        inner = [a for a in args if a is not type(None)][0]
        return _python_type_to_json_schema(inner)
    if origin is list:
        item_type = _python_type_to_json_schema(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item_type}
    if origin is dict:
        return {"type": "object"}

    mapping = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
    }
    return mapping.get(t, {"type": "string"})


def tool(fn: Callable | None = None, *, schema_only: bool = False) -> Callable:
    """Decorator that attaches a JSON-schema tool definition to a function.

    Uses the function's docstring, parameter annotations, and defaults to
    build the schema automatically.

    Use ``@tool(schema_only=True)`` for tools whose schema is registered but
    whose execution is handled by the engine (e.g. delegation, memory).  These
    are excluded from the registry's callable table — the engine intercepts
    them before ``execute_async`` is reached.
    """
    def decorator(fn: Callable) -> Callable:
        hints = get_type_hints(fn)
        sig = inspect.signature(fn)
        doc = inspect.getdoc(fn) or ""

        lines = doc.strip().splitlines()
        description = lines[0] if lines else fn.__name__

        param_docs: dict[str, str] = {}
        for line in lines[1:]:
            line = line.strip().lstrip("-").strip()
            if ":" in line:
                pname, pdesc = line.split(":", 1)
                pname = pname.strip()
                if pname in sig.parameters:
                    param_docs[pname] = pdesc.strip()

        properties: dict[str, Any] = {}
        required: list[str] = []
        for name, param in sig.parameters.items():
            prop = _python_type_to_json_schema(hints.get(name, str))
            if name in param_docs:
                prop["description"] = param_docs[name]
            properties[name] = prop
            if param.default is inspect.Parameter.empty:
                required.append(name)

        fn._tool_schema = {
            "type": "function",
            "function": {
                "name": fn.__name__,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
        fn._schema_only = schema_only
        return fn

    if fn is not None:
        return decorator(fn)
    return decorator


class ToolRegistry:
    """Auto-discovers all @tool-decorated functions in the tools package."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}
        self._schemas: dict[str, dict] = {}
        self._discover()

    def _discover(self) -> None:
        """Import all modules in tools/ and collect decorated functions."""
        tools_dir = Path(__file__).parent
        for info in pkgutil.iter_modules([str(tools_dir)]):
            if info.name.startswith("_"):
                continue
            module = importlib.import_module(f".{info.name}", package=__package__)
            for _name, obj in inspect.getmembers(module, inspect.isfunction):
                if hasattr(obj, "_tool_schema"):
                    self._schemas[obj.__name__] = obj._tool_schema
                    if not getattr(obj, "_schema_only", False):
                        self._tools[obj.__name__] = obj

    def get_schema(self, name: str) -> dict | None:
        return self._schemas.get(name)

    def get_schemas(self, names: list[str] | None = None) -> list[dict]:
        """Return schemas for the given tool names, or all if names is None."""
        if names is None:
            return list(self._schemas.values())
        return [self._schemas[n] for n in names if n in self._schemas]

    def list_tools(self) -> list[str]:
        return sorted(self._schemas.keys())

    async def execute_async(self, name: str, arguments: dict) -> str:
        """Execute a tool by name (async). Wraps sync tools via asyncio.to_thread."""
        fn = self._tools.get(name)
        if fn is None:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            if inspect.iscoroutinefunction(fn):
                result = await fn(**arguments)
            else:
                result = await asyncio.to_thread(fn, **arguments)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})
