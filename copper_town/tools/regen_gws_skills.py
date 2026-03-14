"""Regenerate gws skill files from fresh CLI help output via LLM."""

from __future__ import annotations

import subprocess
from pathlib import Path

import litellm
import yaml

from ..config import MODEL, SKILLS_DIR
from ..utils import parse_markdown_frontmatter


def _bump_patch(v: str) -> str:
    parts = v.split(".") if v else []
    if len(parts) == 3:
        parts[2] = str(int(parts[2]) + 1)
    elif len(parts) == 2:
        parts.append("1")
    else:
        return "1.0.0"
    return ".".join(parts)


def _derive_cli_help(skill_name: str) -> str:
    """Derive the --help command from a skill name when cliHelp is not in frontmatter."""
    # Strip gws- prefix
    rest = skill_name.removeprefix("gws-")
    if not rest or rest == "shared":
        return "gws --help"
    if rest.startswith("workflow-"):
        workflow_name = rest[len("workflow-"):]
        return f"gws workflow +{workflow_name} --help"
    return f"gws {rest} --help"


def _gws_skill_files() -> list[Path]:
    gws_dir = SKILLS_DIR / "gws"
    if not gws_dir.exists():
        return []
    return sorted(gws_dir.glob("*.md"))


async def regen_gws_skills(
    filter_names: list[str] | None = None,
    model: str | None = None,
) -> list[dict]:
    """Regenerate gws skill files from fresh CLI help output.

    Args:
        filter_names: If provided, only regenerate skills whose name or stem
                      contains any of these strings (case-insensitive).
        model: LiteLLM model string to use; falls back to config.MODEL.

    Returns:
        List of dicts with keys: skill, status, path, error.
    """
    effective_model = model or MODEL
    results: list[dict] = []

    skill_files = _gws_skill_files()
    if not skill_files:
        return results

    for path in skill_files:
        skill_name = path.stem

        # Apply optional filter
        if filter_names:
            if not any(f.lower() in skill_name.lower() for f in filter_names):
                results.append({"skill": skill_name, "status": "skipped", "path": str(path), "error": None})
                continue

        text = path.read_text(encoding="utf-8")
        front, body = parse_markdown_frontmatter(text)

        # Determine CLI help command
        cli_help_cmd: str = (
            front.get("metadata", {}).get("openclaw", {}).get("cliHelp")
            or _derive_cli_help(skill_name)
        )

        # Run CLI help
        try:
            proc = subprocess.run(
                ["bash", "-c", cli_help_cmd],
                capture_output=True,
                text=True,
                timeout=30,
            )
            cli_output = proc.stdout or proc.stderr or "(no output)"
        except Exception as exc:
            results.append({
                "skill": skill_name,
                "status": "error",
                "path": str(path),
                "error": f"CLI error: {exc}",
            })
            continue

        # Call LLM to regenerate body
        system_msg = "You are a technical writer maintaining CLI reference docs. Return only the updated markdown body."
        user_msg = (
            f"Existing skill body:\n\n{body}\n\n"
            f"Fresh CLI output from `{cli_help_cmd}`:\n\n{cli_output}\n\n"
            "Update the skill body: preserve existing headings, structure, cross-references, and tips; "
            "update flags, parameters, and methods to match the fresh CLI output; "
            "add any new flags or resources; remove any that no longer exist. "
            "Return only the updated markdown body — no frontmatter, no code fences around the whole thing."
        )

        try:
            response = await litellm.acompletion(
                model=effective_model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
            )
            new_body = response.choices[0].message.content.strip()
        except Exception as exc:
            results.append({
                "skill": skill_name,
                "status": "error",
                "path": str(path),
                "error": f"LLM error: {exc}",
            })
            continue

        # Bump version in frontmatter
        old_version = front.get("version", "")
        new_version = _bump_patch(old_version) if old_version else ""

        # Reconstruct frontmatter preserving all keys; bump version if present
        if new_version:
            front["version"] = new_version
        new_front_str = yaml.dump(front, default_flow_style=False, allow_unicode=True).strip()
        new_text = f"---\n{new_front_str}\n---\n\n{new_body}\n"

        path.write_text(new_text, encoding="utf-8")
        results.append({
            "skill": skill_name,
            "status": "updated",
            "path": str(path),
            "error": None,
        })

    return results
