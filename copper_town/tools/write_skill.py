"""write_skill tool — create or update skills in skills/generated/."""

from __future__ import annotations

import json
import re

import yaml

from ..config import SKILLS_DIR, _PROVIDER_KEY_MAP
from . import tool

_GENERATED_DIR = SKILLS_DIR / "generated"

# API key patterns derived from config so they stay in sync as new providers are added.
_API_KEY_PATTERNS = [rf"\b{v}\b" for v in _PROVIDER_KEY_MAP.values()]

# Shell-injection patterns are stable and kept hardcoded.
_SHELL_PATTERNS = [
    r"subprocess",
    r"rm\s+-rf",
    r"os\.system",
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__",
]

_FORBIDDEN_PATTERNS = _API_KEY_PATTERNS + _SHELL_PATTERNS

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


@tool
def write_skill(name: str, description: str, body: str) -> str:
    """Create or update a skill file in skills/generated/.

    - name: Slug-format name (lowercase letters and hyphens, e.g. 'summarize-pdf')
    - description: One-sentence description of what the skill does
    - body: Full markdown instructions for the skill (no frontmatter needed). Use real newlines to structure the content — do not escape them as \\n.
    """
    # Normalize double-escaped sequences that some LLMs emit in JSON tool args
    # (e.g. literal \n instead of an actual newline character).
    body = body.replace("\\n", "\n").replace("\\t", "\t")

    # Validate name format
    if not _NAME_RE.match(name):
        return json.dumps({
            "ok": False,
            "error": (
                f"Invalid skill name '{name}'. "
                "Must match ^[a-z0-9][a-z0-9\\-]*$ (lowercase letters, digits, hyphens)."
            ),
        })

    # Validate body is non-empty
    if not body.strip():
        return json.dumps({"ok": False, "error": "Skill body cannot be empty."})

    # Block forbidden patterns in body
    for pattern in _FORBIDDEN_PATTERNS:
        if re.search(pattern, body):
            return json.dumps({
                "ok": False,
                "error": f"Skill body contains forbidden pattern: {pattern}",
            })

    # Ensure generated directory exists
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    skill_path = _GENERATED_DIR / f"{name}.md"

    # Build file content with frontmatter
    frontmatter = yaml.dump({"name": name, "description": description}, default_flow_style=False).strip()
    file_content = f"---\n{frontmatter}\n---\n\n{body.strip()}\n"

    skill_path.write_text(file_content, encoding="utf-8")

    # Invalidate the skills index so the new skill is discoverable immediately
    from .skills import invalidate_index
    invalidate_index()

    return json.dumps({
        "ok": True,
        "path": str(skill_path.relative_to(SKILLS_DIR.parent)),
        "name": name,
        "message": f"Skill '{name}' written to {skill_path.name}. Index invalidated.",
    })
