"""Request-local golden inputs shared by versioning, runners, and coverage.

One read captures each family file. No locks span model calls and no process cache
can hide local fixture edits. Editorial notes do not change an experiment's inputs.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from app.evals.case_schema import validate_case
from app.evals.fixture_files import read_json
from app.evals.paths import GOLDEN_FILES

# Eval-only grading changes expire coverage without changing production AI cache keys.
GRADING_VERSION = 1


def case_identity(key: str, family: str = "") -> str:
    return json.dumps([family, key], separators=(",", ":"), ensure_ascii=False) if family else key


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def case_input_fingerprint(case: dict) -> str:
    """Only model inputs and grading policy determine a case result's validity."""
    return fingerprint({"grading_version": GRADING_VERSION, "given": case["given"], "expected": case["metadata"]["expected"],
                        "contested": case["metadata"].get("contested", False)})


@dataclass(frozen=True)
class DatasetSnapshot:
    families: dict[str, dict]

    def case_fingerprints(self, family: str) -> dict[str, str]:
        judge = family in ("judge", "stability")
        selected = self.families if judge else {family: self.families[family]}
        return {
            case_identity(case["key"], name if judge else ""): case_input_fingerprint(case)
            for name, data in selected.items() for case in data["cases"]
        }


def load_dataset(families: str | Iterable[str] | None = None) -> DatasetSnapshot:
    if families is None:
        names = list(GOLDEN_FILES)
    elif isinstance(families, str):
        names = [families]
    else:
        names = list(dict.fromkeys(families))
    if any(name in ("judge", "stability") for name in names):
        names = list(GOLDEN_FILES)
    paths = {name: GOLDEN_FILES[name] for name in names}
    data = {name: read_json(path) for name, path in paths.items()}
    for name, contents in data.items():
        for case in contents["cases"]:
            validate_case(name, case)
    return DatasetSnapshot(data)
