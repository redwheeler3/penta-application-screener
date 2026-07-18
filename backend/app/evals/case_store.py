"""Read/write the eval CASE fixtures for the in-UI cockpit.

The eval dataset (golden scoring cases + judge cases) is a VERSIONED artifact — it lives in
committed JSON, not the DB, so every case change stays a reviewable git diff (the fidelity
rule and the CI structural guards ride on that). This service lets the Evals tab READ the
cases into tables and WRITE an edited/added case back to the SAME JSON file the CLI and CI
read. The operator still ``git add``/commits deliberately — the UI is an editor over the
versioned file, not a second source of truth.

Write discipline: only these two allowlisted fixture files are ever written, each write is
validated for the family's required shape, and the file's non-``cases`` top-level keys (the
golden ``_comment``) are preserved. A bad payload is refused, never partially written.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.evals.paths import GOLDEN_PATH, JUDGE_CASES_PATH

# eval_key -> (fixture path, required per-case fields). Fields are grouped into by-consumer
# blocks (see each fixture's `_comment`): a top-level `key` plus block objects. Only these
# files are writable.
_FIXTURES: dict[str, tuple[Path, tuple[str, ...]]] = {
    "live_scoring": (GOLDEN_PATH, ("key", "metadata", "input", "judge")),
    "judge": (JUDGE_CASES_PATH, ("key", "metadata", "evidence", "prompt")),
}


class UnknownEvalError(ValueError):
    """The eval key has no editable case fixture (e.g. invariants/stability, which read
    the golden/judge sets — stability has no cases of its own)."""


class CaseValidationError(ValueError):
    """A case payload is missing required fields or an invalid key."""


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def list_cases(eval_key: str) -> list[dict]:
    """Every case for an eval, straight from its committed fixture."""
    if eval_key not in _FIXTURES:
        raise UnknownEvalError(eval_key)
    path, _required = _FIXTURES[eval_key]
    # The golden fixture carries a leading ``_comment`` string in ``cases``-adjacent scope;
    # cases themselves are dicts with a "key". Filter to real cases defensively.
    return [c for c in _load(path).get("cases", []) if isinstance(c, dict) and "key" in c]


def save_case(eval_key: str, case: dict) -> list[dict]:
    """Upsert one case into its fixture by ``key`` (add if new, replace if the key exists),
    validate the family shape, and write the file back preserving other top-level keys.
    Returns the full updated case list. Refuses an invalid payload without writing."""
    if eval_key not in _FIXTURES:
        raise UnknownEvalError(eval_key)
    path, required = _FIXTURES[eval_key]
    key = case.get("key")
    if not key or not isinstance(key, str):
        raise CaseValidationError("case must have a non-empty string 'key'")
    missing = [f for f in required if f not in case or case[f] in (None, "")]
    if missing:
        raise CaseValidationError(f"case is missing required field(s): {', '.join(missing)}")

    data = _load(path)
    cases = data.get("cases", [])
    replaced = False
    for i, existing in enumerate(cases):
        if isinstance(existing, dict) and existing.get("key") == key:
            cases[i] = case
            replaced = True
            break
    if not replaced:
        cases.append(case)
    data["cases"] = cases
    # Match the on-disk formatting the fixtures already use (indent=2). Not sort_keys: the
    # golden file keeps ``_comment`` first by insertion order, and case field order is
    # meaningful for readability in the diff.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return [c for c in cases if isinstance(c, dict) and "key" in c]
