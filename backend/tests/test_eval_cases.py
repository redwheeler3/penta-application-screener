"""The eval case store — reading and writing the versioned case fixtures.

Writes go to a TEMP copy (via monkeypatching the fixture registry), never the real
committed files, so the test suite can't mutate the dataset. Covers: list, add (append),
edit (upsert by key), preservation of non-`cases` top-level keys (the golden `_comment`),
and validation refusals.
"""

import json

import pytest

from app.evals import case_store


@pytest.fixture
def golden_file(tmp_path, monkeypatch):
    """Point the golden eval at a temp fixture; yield its path. Restores nothing (the
    registry is module-level, so monkeypatch undoes it after the test)."""
    path = tmp_path / "scoring_golden.json"
    path.write_text(json.dumps({
        "_comment": "keep me",
        "cases": [
            {
                "key": "a",
                "metadata": {"expect": {"score_equals": 0.0}},
                "input": {"applicant": {"facts": {}}, "dimension": {"key": "d"}},
                "judge": {"question": "defensible?"},
            },
        ],
    }))
    reg = dict(case_store._FIXTURES)
    reg["live_scoring"] = (path, reg["live_scoring"][1])
    monkeypatch.setattr(case_store, "_FIXTURES", reg)
    return path


def test_list_cases_reads_only_real_cases(golden_file) -> None:
    cases = case_store.list_cases("live_scoring")
    assert [c["key"] for c in cases] == ["a"]


def test_save_new_case_appends(golden_file) -> None:
    new = {
        "key": "b",
        "metadata": {"expect": {"score_min": 0.5}},
        "input": {"applicant": {"facts": {}}, "dimension": {"key": "d"}},
        "judge": {"question": "defensible?"},
    }
    cases = case_store.save_case("live_scoring", new)
    assert [c["key"] for c in cases] == ["a", "b"]
    # Persisted to disk, and the _comment top-level key survived.
    on_disk = json.loads(golden_file.read_text())
    assert on_disk["_comment"] == "keep me"
    assert [c["key"] for c in on_disk["cases"]] == ["a", "b"]


def test_save_existing_key_upserts_in_place(golden_file) -> None:
    edited = {
        "key": "a",
        "metadata": {"expect": {"score_equals": 0.0}},
        "input": {"applicant": {"facts": {"x": 1}}, "dimension": {"key": "d"}},
        "judge": {"question": "defensible?"},
    }
    cases = case_store.save_case("live_scoring", edited)
    assert len(cases) == 1  # replaced, not appended
    assert cases[0]["input"]["applicant"]["facts"] == {"x": 1}


def test_save_rejects_missing_required_field(golden_file) -> None:
    with pytest.raises(case_store.CaseValidationError):
        case_store.save_case("live_scoring", {"key": "c", "input": {}})  # no metadata/judge


def test_save_rejects_blank_key(golden_file) -> None:
    with pytest.raises(case_store.CaseValidationError):
        case_store.save_case("live_scoring", {"key": "", "metadata": {}, "input": {}, "judge": {}})


def test_unknown_eval_raises(golden_file) -> None:
    with pytest.raises(case_store.UnknownEvalError):
        case_store.list_cases("invariants")
