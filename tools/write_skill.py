"""write_skill tool — create or update skills in skills/generated/."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from config import SKILLS_DIR
from tools import tool

_GENERATED_DIR = SKILLS_DIR / "generated"

_FORBIDDEN_PATTERNS = [
    r"ANTHROPIC_API_KEY",
    r"OPENAI_API_KEY",
    r"XAI_API_KEY",
    r"GEMINI_API_KEY",
    r"GROQ_API_KEY",
    r"subprocess",
    r"rm\s+-rf",
    r"os\.system",
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__",
]

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

    # Validate the written file: must have parseable frontmatter and non-empty body
    written = skill_path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", written, re.DOTALL)
    if not m:
        skill_path.unlink(missing_ok=True)
        return json.dumps({"ok": False, "error": "Written file failed frontmatter validation."})
    try:
        parsed_front = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        skill_path.unlink(missing_ok=True)
        return json.dumps({"ok": False, "error": f"Written file has invalid YAML frontmatter: {e}"})
    if not m.group(2).strip():
        skill_path.unlink(missing_ok=True)
        return json.dumps({"ok": False, "error": "Written file has empty body."})
    if not parsed_front.get("name"):
        skill_path.unlink(missing_ok=True)
        return json.dumps({"ok": False, "error": "Written file is missing 'name' in frontmatter."})

    # Invalidate the skills index so the new skill is discoverable immediately
    import tools.skills as skills_mod
    with skills_mod._INDEX_LOCK:
        skills_mod._INDEX = None

    return json.dumps({
        "ok": True,
        "path": str(skill_path.relative_to(SKILLS_DIR.parent)),
        "name": name,
        "message": f"Skill '{name}' written to {skill_path.name}. Index invalidated.",
    })
