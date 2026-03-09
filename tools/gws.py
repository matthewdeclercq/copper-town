"""Google Workspace CLI tool wrapper."""

from __future__ import annotations

import json
import re
import subprocess

from tools import tool

# Only allow lowercase alphanumeric tokens separated by single spaces.
# This matches all real gws subcommands (e.g. "drive files list") while
# blocking flag injection like "--credentials /evil" or "$(cmd)".
_COMMAND_RE = re.compile(r"^[a-z0-9]+(\s[a-z0-9]+)*$")


@tool
def gws(
    command: str,
    params: str = "",
    json_body: str = "",
    page_all: bool = False,
    dry_run: bool = False,
) -> str:
    """Run a Google Workspace CLI (gws) command and return the JSON response.

    - command: Space-separated gws subcommand, e.g. "drive files list" or "gmail users messages send"
    - params: JSON string of URL/query parameters, e.g. '{"pageSize": 10}'
    - json_body: JSON string for the request body, e.g. '{"name": "My File"}'
    - page_all: If true, auto-paginate and return NDJSON (one JSON object per line)
    - dry_run: If true, validate locally without calling the API
    """
    if not _COMMAND_RE.match(command):
        return json.dumps({
            "error": (
                "Invalid command format. Use only lowercase letters, digits, and spaces "
                "(e.g. 'drive files list'). Flags must not be included in the command."
            )
        })

    if params:
        try:
            json.loads(params)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in 'params'."})

    if json_body:
        try:
            json.loads(json_body)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in 'json_body'."})

    cmd = ["gws"] + command.split()

    if params:
        cmd += ["--params", params]
    if json_body:
        cmd += ["--json", json_body]
    if page_all:
        cmd.append("--page-all")
    if dry_run:
        cmd.append("--dry-run")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        return json.dumps({"error": error, "command": " ".join(cmd)})

    output = result.stdout.strip()
    if not output:
        return json.dumps({"ok": True})

    # page-all returns NDJSON — return as-is for the agent to parse
    if page_all:
        return output

    try:
        return json.dumps(json.loads(output))
    except json.JSONDecodeError:
        return output
