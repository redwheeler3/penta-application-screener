"""Publish versioned eval JSON with complete-file replacement."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, RLock

_LOCKS: dict[Path, RLock] = {}
_LOCKS_GUARD = Lock()


def fixture_lock(path: Path) -> RLock:
    """One file owns its read/modify/write fence and Windows handle lifetime."""
    resolved = path.resolve()
    with _LOCKS_GUARD:
        if resolved not in _LOCKS:
            _LOCKS[resolved] = RLock()
        return _LOCKS[resolved]


def read_json(path: Path) -> dict:
    """Read a complete UTF-8 snapshot; parsing can happen after releasing the handle."""
    with fixture_lock(path):
        content = path.read_text(encoding="utf-8")
    return json.loads(content)


def write_json(path: Path, data: dict, *, sort_keys: bool = False) -> None:
    """Keep the prior file intact on failure; no reader can see a partial rewrite."""
    content = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=sort_keys, allow_nan=False) + "\n"
    with fixture_lock(path):
        _replace(path, content)


def _replace(path: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=path.name + ".", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
