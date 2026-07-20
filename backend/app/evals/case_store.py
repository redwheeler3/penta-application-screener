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

import json
from pathlib import Path

from app.evals.paths import (
    CONSOLIDATION_GOLDEN_PATH,
    DECOMPOSITION_GOLDEN_PATH,
    GOLDEN_PATH,
    MATCHING_GOLDEN_PATH,
    SCREENING_GOLDEN_PATH,
)

# eval_key -> (fixture path, required per-case fields). Fields are grouped into by-consumer
# blocks (see each fixture's `_comment` and docs/eval-case-schema.md): a top-level `key`
# plus block objects (`given` = prompt input; `metadata` = harness-only). Only these files
# are writable.
_FIXTURES: dict[str, tuple[Path, tuple[str, ...]]] = {
    "scoring": (GOLDEN_PATH, ("key", "metadata", "given")),
    "consolidation": (CONSOLIDATION_GOLDEN_PATH, ("key", "metadata", "given")),
    "matching": (MATCHING_GOLDEN_PATH, ("key", "metadata", "given")),
    "decomposition": (DECOMPOSITION_GOLDEN_PATH, ("key", "metadata", "given")),
    "screening": (SCREENING_GOLDEN_PATH, ("key", "metadata", "given")),
}


class UnknownEvalError(ValueError):
    """The eval key has no editable case fixture (e.g. invariants; or judge/stability, which
    read every pass's golden set and own no case files of their own)."""


class CaseValidationError(ValueError):
    """A case payload is missing required fields or an invalid key."""


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def list_cases(eval_key: str) -> list[dict]:
    """Every case for an eval, straight from its committed fixture. The special key ``judge``
    is READ-ONLY and AGGREGATED: it returns every pass's golden cases (the judge owns no files,
    it audits them all), each tagged with its ``pass`` so the Judge tab can group. It is not in
    ``_FIXTURES``, so ``save_case('judge', …)`` correctly refuses (nothing to write to)."""
    if eval_key == "judge":
        out: list[dict] = []
        for pass_name, live_key in _BACKGROUND_PASSES.items():
            path, _ = _FIXTURES[live_key]
            for c in _load(path).get("cases", []):
                if isinstance(c, dict) and "key" in c:
                    c.setdefault("metadata", {}).setdefault("pass", pass_name)
                    out.append(c)
        return out
    if eval_key not in _FIXTURES:
        raise UnknownEvalError(eval_key)
    path, _required = _FIXTURES[eval_key]
    # The golden fixture carries a leading ``_comment`` string in ``cases``-adjacent scope;
    # cases themselves are dicts with a "key". Filter to real cases defensively.
    return [c for c in _load(path).get("cases", []) if isinstance(c, dict) and "key" in c]


def save_case(eval_key: str, case: dict) -> list[dict]:
    """Upsert one case into its fixture by ``key`` (add if new, replace if the key exists),
    validate the family shape, and write the file back preserving other top-level keys.
    Returns the full updated case list. Refuses an invalid payload without writing.

    The aggregated ``judge`` key owns no file, so a judge-tab save is ROUTED to the case's own
    pass file (by ``metadata.pass``) and the re-aggregated judge list is returned — so a case
    edited from the Judge tab lands in the same golden file its pass tab writes to."""
    if eval_key == "judge":
        pass_name = (case.get("metadata") or {}).get("pass")
        if pass_name not in _BACKGROUND_PASSES:
            raise CaseValidationError(
                f"judge case metadata.pass must name a known pass ({', '.join(_BACKGROUND_PASSES)}), got {pass_name!r}"
            )
        save_case(_BACKGROUND_PASSES[pass_name], case)
        return list_cases("judge")
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


# The pass whose golden file each editable judge_background lives in. Keyed by the pass name
# the Judge tab groups by (matches JudgeCase.pass_name), value is the writable eval key.
_BACKGROUND_PASSES: dict[str, str] = {
    "scoring": "scoring",
    "consolidation": "consolidation",
    "matching": "matching",
    "decomposition": "decomposition",
    "screening": "screening",
}


def get_background(pass_name: str) -> str:
    """The editable ``judge_background`` (what the pass does, shown to the blind judge) for one
    pass, read from its golden file. Empty string if unset. Unknown pass → UnknownEvalError."""
    if pass_name not in _BACKGROUND_PASSES:
        raise UnknownEvalError(pass_name)
    path, _ = _FIXTURES[_BACKGROUND_PASSES[pass_name]]
    return _load(path).get("judge_background", "")


def save_background(pass_name: str, background: str) -> str:
    """Write one pass's ``judge_background`` to its golden file (preserving cases + other
    top-level keys). The operator commits the file to git deliberately. Returns the saved
    text. Unknown pass → UnknownEvalError."""
    if pass_name not in _BACKGROUND_PASSES:
        raise UnknownEvalError(pass_name)
    if not isinstance(background, str) or not background.strip():
        raise CaseValidationError("judge_background must be a non-empty string")
    path, _ = _FIXTURES[_BACKGROUND_PASSES[pass_name]]
    data = _load(path)
    data["judge_background"] = background
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return background
