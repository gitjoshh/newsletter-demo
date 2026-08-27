"""Shared helpers for tools. Keep this thin: env loading, paths, and I/O only.

Every tool script should be runnable standalone from the project root:

    python tools/some_tool.py --arg value

Tools print a JSON object to stdout on success and exit non-zero with a
message on stderr on failure, so the agent can parse results deterministically.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

# Project root = two levels up from this file (tools/lib/common.py)
ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / ".tmp"
WORKFLOWS = ROOT / "workflows"
PROJECT_CONFIG = ROOT / "config"
STATE = ROOT / "state"


def load_env() -> None:
    """Load .env from the project root. Safe to call multiple times."""
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env")


def require_env(name: str) -> str:
    """Return an env var or exit with a clear message."""
    load_env()
    val = os.getenv(name)
    if not val:
        fail(f"Missing required environment variable: {name} (set it in .env)")
    return val


def tmp_path(*parts: str) -> Path:
    """Build a path inside .tmp/, creating parent dirs."""
    p = TMP.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def state_path(*parts: str) -> Path:
    """Build a path inside state/, creating parent dirs. Persists across runs."""
    p = STATE.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_json_config(path: Path) -> dict:
    """Read a config/*.json file, failing with a clear message if it is missing or bad."""
    if not path.exists():
        fail(f"Missing config file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"Config file {path} is not valid JSON: {e}")
    return {}  # unreachable


def emit(data: dict) -> None:
    """Print a JSON result to stdout and exit 0."""
    print(json.dumps(data, indent=2, default=str))
    sys.exit(0)


def fail(msg: str, code: int = 1) -> None:
    """Print an error to stderr and exit non-zero."""
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)
