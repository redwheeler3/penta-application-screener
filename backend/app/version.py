"""The running app's version — a single source of truth for stamping artifacts (e.g.
feedback rows) with the build they came from.

Read once from ``pyproject.toml`` (the same value published there), so the version lives
in exactly one place. The package isn't installed with metadata in dev, so we parse the
file directly rather than via ``importlib.metadata``; a missing/unparseable file falls
back to ``"unknown"`` so a stamp is never load-bearing enough to fail a request.
"""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@cache
def app_version() -> str:
    try:
        data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"
