"""Google Workspace CLI tool wrapper."""

from __future__ import annotations

import json
import re
import subprocess
import threading

from . import tool
from ..utils import resolve_safe_path

# Allow lowercase alphanumeric, hyphens, and + for subcommands.
# Each token must start with an alphanumeric or + (prevents --flag injection).
# Matches: "drive files list", "admin-reports activities list", "workflow +standup-report"
_COMMAND_RE = re.compile(r"^[a-z0-9+][a-z0-9+\-]*(\s[a-z0-9+][a-z0-9+\-]*)*$")
_gws_lock = threading.Lock()
_AUTH_KEYWORDS = frozenset({"keyring", "auth", "credential", "token"})


def _validate_json(value: str, field: str) -> str | None:
    """Return error JSON if value is non-empty invalid JSON, else None."""
    if not value:
        return None
    try:
        json.loads(value)
    except json.JSONDecodeError:
        return json.dumps({"error": f"Invalid JSON in '{field}'."})
    return None


@tool
def gws(
    command: str,
    params: str = "",
    json_body: str = "",
    page_all: bool = False,
    page_limit: int = 0,
    page_delay: int = 0,
    upload: str = "",
    output: str = "",
    api_version: str = "",
    dry_run: bool = False,
) -> str:
    """Run a Google Workspace CLI (gws) command and return the JSON response.

    - command: Space-separated gws subcommand, e.g. "drive files list", "admin-reports activities list", "workflow +standup-report"
    - params: JSON string of URL/query parameters, e.g. '{"pageSize": 10}'
    - json_body: JSON string for the request body, e.g. '{"name": "My File"}'
    - page_all: If true, auto-paginate and return NDJSON (one JSON object per line)
    - page_limit: Max pages to fetch with page_all (default: 10, 0 = use CLI default)
    - page_delay: Delay between pages in ms with page_all (0 = use CLI default)
    - upload: Local file path to upload as media content (e.g. for drive files create)
    - output: Local file path to write binary response to (e.g. for drive files download)
    - api_version: Override the API version, e.g. "v2" or "v3"
    - dry_run: If true, validate locally without calling the API
    """
    if not _COMMAND_RE.match(command):
        return json.dumps({
            "error": (
                "Invalid command format. Use only lowercase letters, digits, hyphens, "
                "+ and spaces (e.g. 'drive files list', 'admin-reports activities list', "
                "'workflow +standup-report'). Flags must not be included in the command."
            )
        })

    if err := _validate_json(params, "params"):
        return err
    if err := _validate_json(json_body, "json_body"):
        return err

    if upload and not resolve_safe_path(upload):
        return json.dumps({"error": f"Upload path '{upload}' is outside allowed directories."})

    if output and not resolve_safe_path(output):
        return json.dumps({"error": f"Output path '{output}' is outside allowed directories."})

    cmd = ["gws"] + command.split()

    if params:
        cmd += ["--params", params]
    if json_body:
        cmd += ["--json", json_body]
    if page_all:
        cmd.append("--page-all")
    if page_limit > 0:
        cmd += ["--page-limit", str(page_limit)]
    if page_delay > 0:
        cmd += ["--page-delay", str(page_delay)]
    if upload:
        cmd += ["--upload", upload]
    if output:
        cmd += ["--output", output]
    if api_version:
        cmd += ["--api-version", api_version]
    if dry_run:
        cmd.append("--dry-run")

    try:
        with _gws_lock:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Command timed out after 120 seconds.", "command": " ".join(cmd)})

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        err_lower = error.lower()
        if any(kw in err_lower for kw in _AUTH_KEYWORDS):
            return json.dumps({
                "error": "gws authentication failure — credentials could not be read from keyring. "
                         "The user must run `gws auth login` to refresh credentials. Do not retry this command.",
                "command": " ".join(cmd),
            })
        return json.dumps({"error": error, "command": " ".join(cmd)})

    output_text = result.stdout.strip()
    if not output_text:
        return json.dumps({"ok": True})

    # page-all returns NDJSON — return as-is for the agent to parse
    if page_all:
        return output_text

    try:
        return json.dumps(json.loads(output_text))
    except json.JSONDecodeError:
        return output_text
