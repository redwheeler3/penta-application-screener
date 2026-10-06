"""Read/write the eval CASE fixtures for the in-UI cockpit.

The eval dataset (the five per-pass golden files) is a VERSIONED artifact — it lives in
committed JSON, not the DB, so every case change stays a reviewable git diff (the fidelity
rule and the CI structural guards ride on that). This service lets the Evals tab READ the
cases into tables and WRITE an edited/added case back to the SAME JSON file the CLI and CI
read. The operator still ``git add``/commits deliberately — the UI is an editor over the
versioned file, not a second source of truth.

Write discipline: only the allowlisted per-pass golden files are ever written, each write is
validated for the family's required shape, and the file's non-``cases`` top-level keys (the
``_comment`` and ``judge_background``) are preserved. A bad payload is refused, never
partially written.
"""

from __future__ import annotations

from app.evals.case_schema import CaseValidationError, validate_case
from app.evals.fixture_files import fixture_lock, read_json, write_json
from app.evals.paths import GOLDEN_FILES

# The allowlisted dataset files share one registry with their readers.
_FIXTURES = GOLDEN_FILES

class UnknownEvalError(ValueError):
    """The eval key has no editable case fixture (e.g. invariants; or judge/stability, which
    read every pass's golden set and own no case files of their own)."""


def _read_fixture(eval_key: str) -> dict:
    return read_json(_FIXTURES[eval_key])


def list_cases(eval_key: str) -> list[dict]:
    """Every case for an eval, straight from its committed fixture. The special key ``judge``
    is aggregated: it returns every pass's golden cases (the judge owns no files,
    it audits them all), each tagged with its ``pass`` so the Judge tab can group.
    Judge edits are routed to the case's own pass by ``save_case``."""
    if eval_key == "judge":
        out: list[dict] = []
        for pass_name in _BACKGROUND_PASSES:
            for c in _read_fixture(pass_name).get("cases", []):
                if isinstance(c, dict) and "key" in c:
                    c.setdefault("metadata", {}).setdefault("pass", pass_name)
                    out.append(c)
        return out
    if eval_key not in _FIXTURES:
        raise UnknownEvalError(eval_key)
    # The golden fixture carries a leading ``_comment`` string in ``cases``-adjacent scope;
    # cases themselves are dicts with a "key". Filter to real cases defensively.
    return [c for c in _read_fixture(eval_key).get("cases", []) if isinstance(c, dict) and "key" in c]


def save_case(eval_key: str, case: dict) -> list[dict]:
    """Upsert one case into its fixture by ``key`` (add if new, replace if the key exists),
    validate the family shape, and write the file back preserving other top-level keys.
    Returns the full updated case list. Refuses an invalid payload without writing.

    The aggregated ``judge`` key owns no file, so a judge-tab save is ROUTED to the case's own
    pass file (by ``metadata.pass``) and the re-aggregated judge list is returned — so a case
    edited from the Judge tab lands in the same golden file its pass tab writes to."""
    if eval_key == "judge":
        metadata = case.get("metadata")
        pass_name = metadata.get("pass") if isinstance(metadata, dict) else None
        if pass_name not in _BACKGROUND_PASSES:
            raise CaseValidationError(
                f"judge case metadata.pass must name a known pass ({', '.join(_BACKGROUND_PASSES)}), got {pass_name!r}"
            )
        save_case(pass_name, case)
        return list_cases("judge")
    if eval_key not in _FIXTURES:
        raise UnknownEvalError(eval_key)
    validate_case(eval_key, case)
    path, key = _FIXTURES[eval_key], case["key"]

    with fixture_lock(path):
        data = read_json(path)
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
        write_json(path, data)
        return [c for c in cases if isinstance(c, dict) and "key" in c]


# The passes the judge audits — each has its own golden file (a subset of _FIXTURES: every
# writable pass except the aggregate ``judge`` key). The pass name the Judge tab groups by
# (matches JudgeCase.pass_name) IS the writable eval key, so these index _FIXTURES directly.
_BACKGROUND_PASSES: tuple[str, ...] = (
    "scoring", "consolidation", "matching", "decomposition", "screening",
)


def get_background(pass_name: str) -> str:
    """The editable ``judge_background`` (what the pass does, shown to the blind judge) for one
    pass, read from its golden file. Empty string if unset. Unknown pass → UnknownEvalError."""
    if pass_name not in _BACKGROUND_PASSES:
        raise UnknownEvalError(pass_name)
    return _read_fixture(pass_name).get("judge_background", "")


def save_background(pass_name: str, background: str) -> str:
    """Write one pass's ``judge_background`` to its golden file (preserving cases + other
    top-level keys). The operator commits the file to git deliberately. Returns the saved
    text. Unknown pass → UnknownEvalError."""
    if pass_name not in _BACKGROUND_PASSES:
        raise UnknownEvalError(pass_name)
    if not isinstance(background, str) or not background.strip():
        raise CaseValidationError("judge_background must be a non-empty string")
    path = _FIXTURES[pass_name]
    with fixture_lock(path):
        data = read_json(path)
        data["judge_background"] = background
        write_json(path, data)
        return background
