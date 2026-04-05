"""Sandbox tools: sandboxed file writing and shell command execution."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import uuid
from pathlib import Path

from . import tool

logger = logging.getLogger("copper_town")


def _get_sandbox_dir() -> Path:
    from ..config import BOATSWAIN_SANDBOX_DIR
    BOATSWAIN_SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    return BOATSWAIN_SANDBOX_DIR


def _resolve_sandbox_path(path: str) -> Path | None:
    """Resolve *path* within the sandbox. Returns None if the resolved path escapes it."""
    sandbox = _get_sandbox_dir()
    try:
        p = Path(path).expanduser()
        # Relative paths resolve inside the sandbox; absolute paths must still be inside it.
        resolved = (sandbox / p).resolve() if not p.is_absolute() else p.resolve()
        resolved.relative_to(sandbox)  # raises ValueError if outside
        return resolved
    except Exception:
        return None


def _docker_available() -> bool:
    """Return True if the docker CLI is on PATH and the daemon is reachable."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _run_via_docker(command: str, sandbox: Path, timeout: int) -> str:
    """Execute *command* inside an isolated Docker container mounted at /workspace."""
    from ..config import BOATSWAIN_DOCKER_IMAGE

    container_name = f"copper-town-sandbox-{uuid.uuid4().hex[:8]}"
    docker_cmd = [
        "docker", "run",
        "--rm",
        "--name", container_name,
        "--network", "none",
        "--memory", "512m",
        "--cpus", "1",
        "-v", f"{sandbox}:/workspace",
        "-w", "/workspace",
        BOATSWAIN_DOCKER_IMAGE,
        "sh", "-c", command,
    ]
    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return json.dumps({
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "cwd": "/workspace",
            "mode": "docker",
            "image": BOATSWAIN_DOCKER_IMAGE,
        })
    except subprocess.TimeoutExpired:
        # Best-effort stop — container may have already exited.
        try:
            subprocess.run(["docker", "stop", container_name], capture_output=True, timeout=10)
        except Exception:
            pass
        return json.dumps({"error": f"Command timed out after {timeout}s (container stopped)"})
    except Exception as e:
        return json.dumps({"error": f"Docker execution failed: {e}"})


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file inside the sandbox directory.

    - path: Relative path within the sandbox (e.g. 'src/main.py'). Must not escape the sandbox.
    - content: Full text content to write to the file.
    """
    resolved = _resolve_sandbox_path(path)
    if resolved is None:
        sandbox = _get_sandbox_dir()
        return json.dumps({
            "error": f"Access denied: path must resolve within the sandbox at '{sandbox}'. "
                     "Use relative paths only."
        })
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return json.dumps({
            "ok": True,
            "path": str(resolved),
            "bytes_written": len(content.encode("utf-8")),
        })
    except Exception as e:
        return json.dumps({"error": f"Write failed: {e}"})


@tool
def run_shell(command: str, timeout: int = 30) -> str:
    """Run a shell command inside an isolated Docker container and return its output.

    The container mounts only the sandbox directory, has no network access, and is
    memory/CPU capped. Docker must be running — run_shell will not fall back to the
    host environment.

    - command: Shell command to execute (e.g. 'python main.py', 'ls -la', 'npm test').
    - timeout: Max seconds to wait before killing the container (default: 30, max: 120).
    """
    if not _docker_available():
        return json.dumps({
            "error": "Docker is not running. run_shell requires Docker — start Docker and retry."
        })

    timeout = min(max(1, timeout), 120)
    sandbox = _get_sandbox_dir()
    return _run_via_docker(command, sandbox, timeout)
