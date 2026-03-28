"""Sync gws skill files from upstream GitHub at the installed version."""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
from pathlib import Path

import httpx
import yaml

from ..config import SKILLS_DIR
from ..utils import parse_markdown_frontmatter

GITHUB_API = "https://api.github.com"
UPSTREAM_REPO = "googleworkspace/cli"


def _get_gws_version() -> str | None:
    """Return the installed gws version string, e.g. '0.22.3'."""
    try:
        proc = subprocess.run(["gws", "--version"], capture_output=True, text=True, timeout=10)
        output = (proc.stdout or proc.stderr).strip()
        parts = output.split()
        return parts[1] if len(parts) >= 2 else None
    except Exception:
        return None


def _get_github_token() -> str | None:
    """Return a GitHub token from gh CLI or environment."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        proc = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return None


async def _fetch_skill_list(client: httpx.AsyncClient, tag: str) -> list[str]:
    """Return all skill directory names from the upstream repo at the given tag."""
    url = f"{GITHUB_API}/repos/{UPSTREAM_REPO}/contents/skills"
    resp = await client.get(url, params={"ref": tag})
    resp.raise_for_status()
    return [item["name"] for item in resp.json() if item["type"] == "dir"]


async def _fetch_skill_content(client: httpx.AsyncClient, tag: str, skill_name: str) -> str | None:
    """Fetch and decode the SKILL.md content for a skill from upstream."""
    url = f"{GITHUB_API}/repos/{UPSTREAM_REPO}/contents/skills/{skill_name}/SKILL.md"
    resp = await client.get(url, params={"ref": tag})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("content", "")
    return base64.b64decode(raw.replace("\n", "")).decode("utf-8")


def _convert_frontmatter(content: str) -> str:
    """Convert upstream SKILL.md frontmatter to Copper-Town format."""
    front, body = parse_markdown_frontmatter(content)

    metadata = front.get("metadata") or {}
    openclaw = metadata.get("openclaw") or {}

    new_front: dict = {
        "name": front.get("name", ""),
        "description": front.get("description", ""),
    }
    version = metadata.get("version")
    if version:
        new_front["version"] = str(version)
    cli_help = openclaw.get("cliHelp")
    if cli_help:
        new_front["cli_help"] = cli_help

    front_str = yaml.dump(new_front, default_flow_style=False, allow_unicode=True).strip()
    return f"---\n{front_str}\n---\n\n{body}\n"


async def regen_gws_skills(
    filter_names: list[str] | None = None,
    model: str | None = None,
) -> list[dict]:
    """Sync skills/gws/ to match the upstream repo at the installed gws version.

    Fetches all skills from GitHub, converts frontmatter, writes local files,
    and removes any local files not present upstream.

    Args:
        filter_names: If provided, only sync skills whose name contains any of
                      these strings (case-insensitive). Stale file removal is
                      skipped when a filter is active.
        model: Unused; kept for API compatibility.

    Returns:
        List of dicts with keys: skill, status, path, error.
    """
    version = _get_gws_version()
    if not version:
        print("error: could not determine installed gws version", flush=True)
        return []

    tag = f"v{version}"
    print(f"Syncing gws skills from upstream {tag}...", flush=True)

    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        print("warning: no GitHub token found — unauthenticated requests limited to 60/hour", flush=True)
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        try:
            upstream_names = await _fetch_skill_list(client, tag)
        except Exception as exc:
            print(f"error: could not fetch skill list from GitHub: {exc}", flush=True)
            return []

        print(f"Found {len(upstream_names)} skills upstream.", flush=True)

        to_process = upstream_names
        if filter_names:
            to_process = [n for n in upstream_names if any(f.lower() in n.lower() for f in filter_names)]

        total = len(to_process)
        width = len(str(total))
        gws_dir = SKILLS_DIR / "gws"
        gws_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict] = []

        for i, skill_name in enumerate(to_process, 1):
            print(f"  [{i:>{width}}/{total}] {skill_name}...", end="", flush=True)
            local_path = gws_dir / f"{skill_name}.md"

            try:
                content = await _fetch_skill_content(client, tag, skill_name)
            except Exception as exc:
                print(f" error (fetch: {exc})", flush=True)
                results.append({"skill": skill_name, "status": "error", "path": str(local_path), "error": str(exc)})
                continue

            if content is None:
                print(" skipped (no SKILL.md)", flush=True)
                results.append({"skill": skill_name, "status": "skipped", "path": str(local_path), "error": None})
                continue

            local_path.write_text(_convert_frontmatter(content), encoding="utf-8")
            print(" done", flush=True)
            results.append({"skill": skill_name, "status": "updated", "path": str(local_path), "error": None})

    # Remove local skills not present upstream (only when no filter active)
    if not filter_names:
        upstream_set = set(upstream_names)
        for local_file in sorted(gws_dir.glob("*.md")):
            if local_file.stem not in upstream_set:
                print(f"  removing {local_file.stem} (not in upstream)", flush=True)
                local_file.unlink()

    return results
