"""Built-in tools: file reading and listing."""

from __future__ import annotations

import json

from . import tool
from ..utils import resolve_safe_path


@tool
def read_file(path: str) -> str:
    """Read the contents of a file and return its text.

    - path: Absolute or relative path to the file to read.
    """
    p = resolve_safe_path(path)
    if p is None:
        return json.dumps({"error": f"Access denied: '{path}' is outside allowed directories."})
    if not p.exists():
        return json.dumps({"error": f"File not found: {path}"})
    if not p.is_file():
        return json.dumps({"error": f"Not a file: {path}"})
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return json.dumps({"error": f"Could not read file: {e}"})


@tool
def list_files(path: str, pattern: str = "*") -> str:
    """List files in a directory, optionally filtered by a glob pattern.

    - path: Directory path to list.
    - pattern: Glob pattern to filter files (default: "*").
    """
    p = resolve_safe_path(path)
    if p is None:
        return json.dumps({"error": f"Access denied: '{path}' is outside allowed directories."})
    if not p.exists():
        return json.dumps({"error": f"Directory not found: {path}"})
    if not p.is_dir():
        return json.dumps({"error": f"Not a directory: {path}"})
    matches = sorted(str(f.relative_to(p)) for f in p.glob(pattern) if f.is_file())
    return json.dumps({"files": matches, "count": len(matches)})
