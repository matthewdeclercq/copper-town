"""Shared utilities for the Copper-Town engine."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import yaml

from .config import ALLOWED_READ_DIRS

logger = logging.getLogger("copper_town")


def interpolate_env(text: str, fallback_original: bool = True) -> str:
    """Replace ${VAR_NAME} placeholders with environment variable values.

    If *fallback_original* is True (default), unresolved placeholders are
    preserved as-is.  When False, they are replaced with an empty string.
    """
    default_fn = (lambda m: m.group(0)) if fallback_original else (lambda m: "")
    return re.sub(r"\$\{(\w+)\}", lambda m: os.getenv(m.group(1)) or default_fn(m), text)


def resolve_safe_path(path: str) -> Path | None:
    """Resolve *path* and confirm it falls under an allowed root.

    Relative paths are resolved against ROOT_DIR so agents don't need
    to know the absolute project path.
    Returns the resolved Path on success, or None if access is denied.
    """
    from .config import ROOT_DIR

    try:
        p = Path(path).expanduser()
        resolved = (ROOT_DIR / p).resolve() if not p.is_absolute() else p.resolve()
    except Exception:
        return None
    for allowed in ALLOWED_READ_DIRS:
        try:
            resolved.relative_to(allowed)
            return resolved
        except ValueError:
            continue
    return None


def parse_bullet_entries(text: str) -> list[str]:
    """Extract entries from bullet-list text. Handles '- ' prefixed and bare lines."""
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            entries.append(line[2:].strip())
        elif line:
            entries.append(line)
    return entries


def parse_markdown_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_str) from a markdown file with YAML frontmatter."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    try:
        front = yaml.safe_load(m.group(1)) or {}
    except Exception:
        logger.debug("Failed to parse YAML frontmatter: %s", m.group(1)[:200])
        front = {}
    return front, m.group(2).strip()
