"""Skills library tools: search and load skills dynamically."""

from __future__ import annotations

import json
import re
from pathlib import Path

from config import SKILLS_DIR
from tools import tool


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body) from a markdown file."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    try:
        import yaml
        front = yaml.safe_load(m.group(1)) or {}
    except Exception:
        front = {}
    return front, m.group(2).strip()


def _skill_files() -> list[Path]:
    """All .md files in skills/ excluding _global/ subdirectory."""
    if not SKILLS_DIR.exists():
        return []
    return [
        p for p in SKILLS_DIR.rglob("*.md")
        if "_global" not in p.parts
    ]


_INDEX: dict[str, dict] | None = None


def _get_index() -> dict[str, dict]:
    """Build and cache a name-keyed index of all skills."""
    global _INDEX
    if _INDEX is None:
        _INDEX = {}
        for path in sorted(_skill_files()):
            text = path.read_text(encoding="utf-8")
            front, body = _parse_frontmatter(text)
            name = front.get("name") or path.stem
            desc = front.get("description") or (body.splitlines()[0].lstrip("# ").strip() if body else "")
            _INDEX[name] = {"description": desc, "path": path, "body": body}
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
