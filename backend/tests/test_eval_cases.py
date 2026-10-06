"""The eval case store — reading and writing the versioned case fixtures.

Writes go to a TEMP copy (via monkeypatching the fixture registry), never the real
committed files, so the test suite can't mutate the dataset. Covers: list, add (append),
edit (upsert by key), preservation of non-`cases` top-level keys (the golden `_comment`),
and validation refusals.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.evals import case_store, fixture_files


@pytest.fixture
def golden_file(tmp_path, monkeypatch):
    """Point the golden eval at a temp fixture; yield its path. Restores nothing (the
    registry is module-level, so monkeypatch undoes it after the test)."""
    path = tmp_path / "scoring_golden.json"
    path.write_text(json.dumps({
        "_comment": "keep me",
        "judge_background": "keep me too",
        "cases": [
            {
                "key": "a",
                "metadata": {"expected": {"score_min": -0.1, "score_max": 0.1}},
                "given": {"applicant": {"facts": {}}, "dimension": {"key": "d", "name": "D", "definition": "Synthetic", "high_end": "High", "low_end": "Low"}},
            },
        ],
    }))
    reg = dict(case_store._FIXTURES)
    reg["scoring"] = path
    monkeypatch.setattr(case_store, "_FIXTURES", reg)
    return path


def test_list_cases_reads_only_real_cases(golden_file) -> None:
    cases = case_store.list_cases("scoring")
    assert [c["key"] for c in cases] == ["a"]


def test_save_new_case_appends(golden_file) -> None:
    new = {
        "key": "b",
        "metadata": {"expected": {"score_min": 0.5}},
        "given": {"applicant": {"facts": {}}, "dimension": {"key": "d", "name": "D", "definition": "Synthetic", "high_end": "High", "low_end": "Low"}},
    }
    cases = case_store.save_case("scoring", new)
    assert [c["key"] for c in cases] == ["a", "b"]
    # Persisted to disk, and both non-cases top-level keys survived.
    on_disk = json.loads(golden_file.read_text())
    assert on_disk["_comment"] == "keep me"
    assert on_disk["judge_background"] == "keep me too"
    assert [c["key"] for c in on_disk["cases"]] == ["a", "b"]


def test_save_existing_key_upserts_in_place(golden_file) -> None:
    edited = {
        "key": "a",
        "metadata": {"expected": {"score_min": -0.1, "score_max": 0.1}},
        "given": {"applicant": {"facts": {"x": 1}}, "dimension": {"key": "d", "name": "D", "definition": "Synthetic", "high_end": "High", "low_end": "Low"}},
    }
    cases = case_store.save_case("scoring", edited)
    assert len(cases) == 1  # replaced, not appended
    assert cases[0]["given"]["applicant"]["facts"] == {"x": 1}


def test_save_rejects_missing_required_field(golden_file) -> None:
    with pytest.raises(case_store.CaseValidationError):
        case_store.save_case("scoring", {"key": "c", "given": {}})  # no metadata


def test_save_rejects_blank_key(golden_file) -> None:
    with pytest.raises(case_store.CaseValidationError):
        case_store.save_case("scoring", {"key": "", "metadata": {}, "given": {}})


def test_unknown_eval_raises(golden_file) -> None:
    with pytest.raises(case_store.UnknownEvalError):
        case_store.list_cases("invariants")


def test_save_judge_case_routes_to_its_pass_file(golden_file) -> None:
    # A judge-tab edit owns no file; it must land in the case's own pass file (by
    # metadata.pass) and come back in the re-aggregated judge list.
    edited = {
        "key": "a",
        "metadata": {"pass": "scoring", "expected": {"score_min": 0.9}},
        "given": {"applicant": {"facts": {"y": 2}}, "dimension": {"key": "d", "name": "D", "definition": "Synthetic", "high_end": "High", "low_end": "Low"}},
    }
    result = case_store.save_case("judge", edited)
    # Written to the (temp) scoring file, upserted in place.
    on_disk = json.loads(golden_file.read_text())
    saved = next(c for c in on_disk["cases"] if c["key"] == "a")
    assert saved["given"]["applicant"]["facts"] == {"y": 2}
    # The returned list is the aggregated judge set (contains the routed case).
    assert any(c["key"] == "a" and c["metadata"].get("pass") == "scoring" for c in result)


def test_save_judge_case_rejects_unknown_pass(golden_file) -> None:
    with pytest.raises(case_store.CaseValidationError):
        case_store.save_case("judge", {"key": "x", "metadata": {"pass": "nope"}, "given": {}})


@pytest.mark.parametrize("second_edit", ["case", "background"])
def test_overlapping_fixture_edits_preserve_both_changes(golden_file, monkeypatch, second_edit) -> None:
    held, release, competing = Event(), Event(), Event()
    write = case_store.write_json

    def pause_first_write(path, data):
        if not held.is_set():
            held.set()
            assert release.wait(5)
        write(path, data)

    monkeypatch.setattr(case_store, "write_json", pause_first_write)

    def save_case(key):
        case = json.loads(golden_file.read_text())["cases"][0]
        case["key"] = key
        return case_store.save_case("scoring", case)

    def save_second():
        competing.set()
        if second_edit == "case":
            return save_case("c")
        return case_store.save_background("scoring", "Updated brief — café")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save_case, "b")
        try:
            assert held.wait(5)
            second = pool.submit(save_second)
            assert competing.wait(5)
            assert not second.done()
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    data = json.loads(golden_file.read_text(encoding="utf-8"))
    assert data["_comment"] == "keep me"
    assert [case["key"] for case in data["cases"]] == (["a", "b", "c"] if second_edit == "case" else ["a", "b"])
    assert data["judge_background"] == ("keep me too" if second_edit == "case" else "Updated brief — café")


def test_failed_publication_preserves_original_and_removes_temporary_file(golden_file, monkeypatch) -> None:
    original = golden_file.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("Synthetic replacement failure")

    monkeypatch.setattr(fixture_files.os, "replace", fail_replace)
    with pytest.raises(OSError, match="Synthetic replacement failure"):
        case_store.save_background("scoring", "Changed brief")
    assert golden_file.read_bytes() == original
    assert list(golden_file.parent.glob("*.tmp")) == []


@pytest.mark.parametrize(("family", "field"), [
    ("scoring", "dimension"), ("matching", "prior"), ("decomposition", "reports"),
    ("consolidation", "pair"), ("screening", "fields"),
])
@pytest.mark.parametrize("invalid", ["missing", "wrong-type"])
def test_nested_validation_keeps_each_family_file_readable(tmp_path, monkeypatch, family, field, invalid) -> None:
    source = case_store._FIXTURES[family]
    path = tmp_path / source.name
    path.write_bytes(source.read_bytes())
    monkeypatch.setitem(case_store._FIXTURES, family, path)
    original = path.read_bytes()
    case = json.loads(original)["cases"][0]
    if invalid == "missing":
        del case["given"][field]
    else:
        case["given"][field] = 7
    with pytest.raises(case_store.CaseValidationError, match=rf"given\.{field}"):
        case_store.save_case(family, case)
    assert path.read_bytes() == original


def test_missing_scoring_pole_is_rejected_by_both_writer_and_reader(golden_file) -> None:
    from app.evals.scoring import load_golden

    data = json.loads(golden_file.read_text())
    case = data["cases"][0]
    del case["given"]["dimension"]["high_end"]
    original = golden_file.read_bytes()
    with pytest.raises(case_store.CaseValidationError, match=r"given\.dimension\.high_end"):
        case_store.save_case("scoring", case)
    assert golden_file.read_bytes() == original
    golden_file.write_text(json.dumps(data))
    with pytest.raises(case_store.CaseValidationError, match=r"given\.dimension\.high_end"):
        load_golden(golden_file)


@pytest.mark.parametrize("family", ["scoring", "matching", "decomposition", "consolidation", "screening"])
def test_valid_family_case_preserves_captured_input_and_metadata(tmp_path, monkeypatch, family) -> None:
    from app.evals.judge import _PASS_FILES, load_cases

    source = case_store._FIXTURES[family]
    path = tmp_path / source.name
    path.write_bytes(source.read_bytes())
    monkeypatch.setitem(case_store._FIXTURES, family, path)
    monkeypatch.setitem(_PASS_FILES, family, path)
    case = json.loads(path.read_text(encoding="utf-8"))["cases"][0]
    case["metadata"]["note"] = "Changed synthetic note"
    case["metadata"]["extra_capture"] = {"kept": True}
    assert case_store.save_case(family, case)[0] == case
    assert any(item.key == case["key"] and item.pass_name == family for item in load_cases())


def test_short_consolidation_pair_and_malformed_judge_metadata_are_rejected() -> None:
    case = case_store.list_cases("consolidation")[0]
    case["given"]["pair"] = case["given"]["pair"][:1]
    with pytest.raises(case_store.CaseValidationError, match=r"given\.pair"):
        case_store.save_case("consolidation", case)
    with pytest.raises(case_store.CaseValidationError, match=r"metadata\.pass"):
        case_store.save_case("judge", {"key": "synthetic", "metadata": [], "given": {}})


@pytest.mark.parametrize(("family", "field"), [("matching", "prior"), ("matching", "new"), ("consolidation", "pair")])
def test_live_named_descriptors_cannot_omit_names(family, field):
    case = case_store.list_cases(family)[0]
    del case["given"][field][0]["name"]
    with pytest.raises(case_store.CaseValidationError, match="name"):
        case_store.save_case(family, case)


@pytest.mark.parametrize("field", ["prior", "new"])
def test_matching_needs_both_sides(field):
    case = case_store.list_cases("matching")[0]
    case["given"][field] = []
    with pytest.raises(case_store.CaseValidationError, match=field):
        case_store.save_case("matching", case)
