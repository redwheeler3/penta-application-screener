"""Fixture validation protects the same raw inputs consumed by live and Judge graders."""

import copy
import json

import pytest

from app.ai.schemas import PetFacts
from app.evals import case_store, screening
from app.evals.case_schema import CaseValidationError, validate_case
from app.evals.dataset import case_identity, load_dataset
from app.evals.paths import GOLDEN_FILES


@pytest.mark.parametrize("family", ["matching", "unknown", None])
def test_conflicting_family_cannot_mutate_fixture(tmp_path, monkeypatch, family):
    original = GOLDEN_FILES["scoring"].read_bytes()
    path = tmp_path / "scoring.json"
    path.write_bytes(original)
    monkeypatch.setitem(case_store._FIXTURES, "scoring", path)
    case = json.loads(original)["cases"][0]
    case["metadata"]["pass"] = family
    with pytest.raises(CaseValidationError, match="owning family"):
        case_store.save_case("scoring", case)
    assert path.read_bytes() == original


def test_judge_list_derives_family_from_file_and_bad_manual_edit_cannot_run(tmp_path, monkeypatch):
    path = tmp_path / "matching.json"
    data = copy.deepcopy(load_dataset("matching").families["matching"])
    data["cases"] = data["cases"][:1]
    data["cases"][0]["key"] = "même clé"
    data["cases"][0]["metadata"]["pass"] = "consolidation"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setitem(GOLDEN_FILES, "matching", path)
    listed = next(case for case in case_store.list_cases("judge") if case["key"] == "même clé")
    assert listed["metadata"]["pass"] == "matching"
    assert case_identity(listed["key"], listed["metadata"]["pass"]) == '["matching","même clé"]'
    with pytest.raises(CaseValidationError, match="owning family"):
        load_dataset("matching")


@pytest.mark.parametrize("expected", [
    {"fires": ["fake_contcat"]}, {"absent": ["fake_contcat"]},
    {"fires": " "}, {"fires": [[]]}, {"fires": "fake_contact|"},
    {"fires": [["fake_contact", " "]]}, {"absent": [""]},
    *({"pets": {"dogs": count}} for count in ["2", True, None, -1]),
    {"pets": {"other_pets": "rabbit"}},
])
def test_invalid_screening_expectations_leave_fixture_unchanged(tmp_path, monkeypatch, expected):
    path = tmp_path / "screening.json"
    original = GOLDEN_FILES["screening"].read_bytes()
    path.write_bytes(original)
    monkeypatch.setitem(case_store._FIXTURES, "screening", path)
    case = json.loads(original)["cases"][0]
    case["metadata"]["expected"] = expected
    with pytest.raises(CaseValidationError):
        case_store.save_case("screening", case)
    assert path.read_bytes() == original


@pytest.mark.parametrize("fires", [" fake_contact ", [" fake_contact "],
    "fake_contact | spam_essay", ["fake_contact | spam_essay"], [[" fake_contact ", "spam_essay"]]])
def test_valid_raw_expectations_have_one_live_and_judge_meaning(fires):
    raw = copy.deepcopy(load_dataset("screening").families["screening"]["cases"][0])
    raw["metadata"]["expected"] = {"fires": fires, "absent": [" minimal_essay "], "pets": {"dogs": 2}}
    validate_case("screening", raw)
    live = screening.load_cases(data={"cases": [raw]})[0]
    blind = screening._case_from_expected(raw["key"], raw["given"], raw["metadata"]["expected"])
    for case in (live, blind):
        assert screening._check(case, ["fake_contact"], PetFacts(dogs=2)) == []
        assert screening._check(case, ["fake_contact", "minimal_essay"], PetFacts(dogs=2))
