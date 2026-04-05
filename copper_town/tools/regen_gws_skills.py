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


async def _fetch_tree(client: httpx.AsyncClient, tag: str) -> dict[str, str]:
    """Fetch the full repo tree and return {skill_name: blob_sha} for all SKILL.md files."""
    url = f"{GITHUB_API}/repos/{UPSTREAM_REPO}/git/trees/{tag}"
    resp = await client.get(url, params={"recursive": "1"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("truncated"):
        print("warning: tree response was truncated; some skills may be missed", flush=True)
    skills: dict[str, str] = {}
    for entry in data.get("tree", []):
        if entry["type"] != "blob":
            continue
        parts = entry["path"].split("/")
        if len(parts) == 3 and parts[0] == "skills" and parts[2] == "SKILL.md":
            skills[parts[1]] = entry["sha"]
    return skills


async def _fetch_blob(client: httpx.AsyncClient, sha: str) -> str | None:
    """Fetch and decode a blob by SHA."""
    url = f"{GITHUB_API}/repos/{UPSTREAM_REPO}/git/blobs/{sha}"
    resp = await client.get(url)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    content = data.get("content", "")
    encoding = data.get("encoding", "base64")
    if encoding == "base64":
        return base64.b64decode(content.replace("\n", "")).decode("utf-8")
    return content


def _read_local_sha(path: Path) -> str | None:
    """Read the _upstream_sha from a local skill file's frontmatter, or None."""
    try:
        text = path.read_text(encoding="utf-8")
        front, _ = parse_markdown_frontmatter(text)
        return front.get("_upstream_sha")
    except Exception:
        return None


def _convert_frontmatter(content: str, upstream_sha: str | None = None) -> str:
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
    if upstream_sha is not None:
        new_front["_upstream_sha"] = upstream_sha

    front_str = yaml.dump(new_front, default_flow_style=False, allow_unicode=True).strip()
    return f"---\n{front_str}\n---\n\n{body}\n"


async def regen_gws_skills(
    filter_names: list[str] | None = None,
    model: str | None = None,
) -> list[dict]:
    """Sync skills/gws/ to match the upstream repo at the installed gws version.

    Uses the Git Trees API for single-call change detection, then only
    fetches blobs for skills whose SHA differs from the local copy.

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
            tree = await _fetch_tree(client, tag)
        except Exception as exc:
            print(f"error: could not fetch tree from GitHub: {exc}", flush=True)
            return []

        upstream_names = sorted(tree.keys())
        to_process = upstream_names
        if filter_names:
            to_process = [n for n in upstream_names if any(f.lower() in n.lower() for f in filter_names)]

        gws_dir = SKILLS_DIR / "gws"
        gws_dir.mkdir(parents=True, exist_ok=True)

        # Diff SHAs to find changed skills
        to_fetch: list[tuple[str, str, Path]] = []  # (name, sha, local_path)
        results: list[dict] = []

        for name in to_process:
            local_path = gws_dir / f"{name}.md"
            upstream_sha = tree[name]
            if _read_local_sha(local_path) == upstream_sha:
                results.append({"skill": name, "status": "unchanged", "path": str(local_path), "error": None})
            else:
                to_fetch.append((name, upstream_sha, local_path))

        print(f"Found {len(upstream_names)} skills upstream, {len(to_fetch)} changed.", flush=True)

        # Fetch changed blobs concurrently
        sem = asyncio.Semaphore(10)

        async def _fetch_and_write(name: str, sha: str, local_path: Path) -> dict:
            async with sem:
                try:
                    content = await _fetch_blob(client, sha)
                except Exception as exc:
                    print(f"  {name}... error ({exc})", flush=True)
                    return {"skill": name, "status": "error", "path": str(local_path), "error": str(exc)}

            if content is None:
                print(f"  {name}... skipped (blob fetch returned empty)", flush=True)
                return {"skill": name, "status": "skipped", "path": str(local_path), "error": None}

            local_path.write_text(_convert_frontmatter(content, upstream_sha=sha), encoding="utf-8")
            print(f"  {name}... updated", flush=True)
            return {"skill": name, "status": "updated", "path": str(local_path), "error": None}

        fetch_results = await asyncio.gather(
            *(_fetch_and_write(name, sha, path) for name, sha, path in to_fetch)
        )
        results.extend(fetch_results)

    # Remove local skills not present upstream (only when no filter active)
    if not filter_names:
        upstream_set = set(upstream_names)
        for local_file in sorted(gws_dir.glob("*.md")):
            if local_file.stem not in upstream_set:
                print(f"  removing {local_file.stem} (not in upstream)", flush=True)
                local_file.unlink()

    return results
