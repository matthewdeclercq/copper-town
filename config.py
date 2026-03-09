"""Configuration: env loading, paths, constants."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# -- Paths --
ROOT_DIR = Path(__file__).resolve().parent
AGENTS_DIR = ROOT_DIR / "agents"
SKILLS_DIR = ROOT_DIR / "skills"
GLOBAL_SKILLS_DIR = SKILLS_DIR / "_global"
TOOLS_DIR = ROOT_DIR / "tools"
MEMORY_DIR = ROOT_DIR / "memory"

# -- Model --
MODEL = os.getenv("MODEL", "xai/grok-4-latest")

# -- Engine limits --
MAX_TOOL_ITERATIONS = 20
MAX_DELEGATION_DEPTH = 3
MAX_CONTEXT_MESSAGES = 40
MAX_PARALLEL_TOOLS = int(os.getenv("MAX_PARALLEL_TOOLS", "4"))
MAX_TOOL_OUTPUT_CHARS = int(os.getenv("MAX_TOOL_OUTPUT_CHARS", "10000"))
MAX_SYSTEM_PROMPT_CHARS = int(os.getenv("MAX_SYSTEM_PROMPT_CHARS", "50000"))
CONTEXT_SUMMARIZE = os.getenv("CONTEXT_SUMMARIZE", "true").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING")

# -- Memory --
MEMORY_MAX_LINES = 100
MEMORY_MIN_MESSAGES = int(os.getenv("MEMORY_MIN_MESSAGES", "12"))
MEMORY_WRITE_MAX_CHARS = int(os.getenv("MEMORY_WRITE_MAX_CHARS", "2000"))
MEMORY_COMPRESS_ENABLED = os.getenv("MEMORY_COMPRESS_ENABLED", "true").lower() == "true"

# -- File access sandboxing --
_raw_allowed = os.getenv("ALLOWED_READ_DIRS", "")
ALLOWED_READ_DIRS: list[Path] = (
    [Path(p).resolve() for p in _raw_allowed.split(":") if p.strip()]
    if _raw_allowed.strip()
    else [ROOT_DIR]
)

_PROVIDER_KEY_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "grok": "XAI_API_KEY",
}


def validate_env() -> None:
    """Raise SystemExit if the required API key for the chosen provider is missing."""
    provider = MODEL.split("/")[0].lower()
    if provider == "ollama":
        return  # No key needed
    required_key = _PROVIDER_KEY_MAP.get(provider)
    if required_key and not os.getenv(required_key):
        sys.exit(
            f"[Config] Missing required environment variable: {required_key}\n"
            f"Set it in your .env file or shell before running.\n"
            f"Example: {required_key}=your-key-here"
        )


validate_env()
