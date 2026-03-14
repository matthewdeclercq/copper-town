"""Skills library tools: search and load skills dynamically."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from ..config import GLOBAL_SKILLS_DIR, SKILLS_DIR
from . import tool
from ..utils import parse_markdown_frontmatter


def _skill_files() -> list[Path]:
    """All .md files in skills/ excluding _global/ subdirectory."""
    if not SKILLS_DIR.exists():
        return []
    return [
        p for p in SKILLS_DIR.rglob("*.md")
        if GLOBAL_SKILLS_DIR.name not in p.parts
    ]


_INDEX: dict[str, dict] | None = None
_INDEX_LOCK = threading.Lock()


def _get_index() -> dict[str, dict]:
    """Build and cache a name-keyed index of all skills (thread-safe)."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    with _INDEX_LOCK:
        if _INDEX is not None:
            return _INDEX  # another thread built it while we waited
        idx: dict[str, dict] = {}
        for path in sorted(_skill_files(), key=lambda p: (1 if "generated" in p.parts else 0, str(p))):
            text = path.read_text(encoding="utf-8")
            front, body = parse_markdown_frontmatter(text)
            name = front.get("name") or path.stem
            desc = front.get("description") or (body.splitlines()[0].lstrip("# ").strip() if body else "")
            idx[name] = {"description": desc, "path": path, "body": body}
        _INDEX = idx
    return _INDEX


@tool
def search_skills(query: str) -> str:
    """Search the skills library by keyword and return matching skill names and descriptions.

    - query: Space-separated keywords to search for (e.g. "send email", "upload drive file").
    """
    keywords = [w.lower() for w in query.split() if w]
    results = []

    for name, entry in _get_index().items():
        haystack = (name + " " + entry["description"]).lower()
        if all(kw in haystack for kw in keywords):
            results.append({"name": name, "description": entry["description"]})
            if len(results) >= 10:
                break

    if not results:
        return json.dumps({"matches": [], "hint": "No skills matched. Try broader keywords."})
    return json.dumps({"matches": results})


@tool
def load_skill(name: str) -> str:
    """Load and return the full instructions for a skill by name.

    - name: The skill name (from search_skills results) or filename stem.
    """
    target = name.lower()
    index = _get_index()

    for skill_name, entry in index.items():
        if skill_name.lower() == target or entry["path"].stem.lower() == target:
            return entry["body"]

    return json.dumps({
        "error": f"Skill '{name}' not found.",
        "hint": "Call search_skills first to find available skill names.",
    })


def invalidate_index() -> None:
    """Clear the cached skills index so it is rebuilt on next access."""
    global _INDEX
    with _INDEX_LOCK:
        _INDEX = None
