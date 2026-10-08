"""Application prompt consumers share submitted ages without forwarding birth dates."""

import json
from copy import deepcopy
from datetime import date

from app.ai import dimension_discovery, dimension_scoring, screening
from app.ai.input_evidence import input_fingerprint
from app.db.models import Application
from app.schemas.applicant.answers import CanonicalApplicationAnswers
from app.services.applications.intake import normalize_answers
from tests.applicant.support import sample_answers
from tests.ranking_support import a_pattern_report


def household():
    answers = sample_answers()
    answers["coApplicant"] = {**answers["applicant"], "firstName": "Morgan", "email": "morgan@example.com",
                              "birthDate": "1988-01-01", "relationship": "Partner"}
    answers["coApplicantEmployment"] = answers["applicantEmployment"]
    answers["coApplicantIncome"] = 60000
    answers["children"] = [{"firstName": "Casey", "lastName": "Ng", "birthDate": "2016-06-01"}]
    canonical = CanonicalApplicationAnswers.model_validate(answers)
    return Application(id=1, raw_row=canonical.model_dump(mode="json"), raw_row_hash="synthetic",
                       normalized=normalize_answers(canonical, as_of_date=date(2026, 4, 11)))


def block(prompt, tag):
    return json.loads(prompt.split(f"<{tag}>\n", 1)[1].split(f"\n</{tag}>", 1)[0])


def test_rendered_screen_and_rank_inputs_use_frozen_ages_without_birth_dates():
    application = household()
    original = deepcopy(application.normalized)
    screen = block(screening.build_prompt(application), "fields")
    discovered = block(dimension_discovery.build_prompt([application]), "applicant_pool")[0]["facts"]
    scored = block(dimension_scoring.build_prompt(application, a_pattern_report().dimensions), "applicant")["facts"]
    assert discovered == scored
    for fields in (screen, discovered, scored):
        assert fields["applicant_age"] == 35
        assert fields["co_applicant_age"] == 38
        assert fields["child_details"][0]["age"] == 9
        assert "birth_date" not in json.dumps(fields)
    assert screen["applicant_name"] == "Avery Ng"
    assert screen["co_applicant_name"] == "Morgan Ng"
    assert screen["child_details"] == [{"first_name": "Casey", "last_name": "Ng", "age": 9}]
    assert discovered["child_details"] == [{"age": 9}]
    assert "name" not in json.dumps(discovered)
    assert application.normalized == original
    assert application.normalized["child_details"][0]["birth_date"] == "2016-06-01"


def test_input_identity_tracks_the_projected_child_fields_for_each_pass():
    application = household()
    normalized = application.normalized
    screen = input_fingerprint(application.raw_row_hash, normalized, "screening")
    score = input_fingerprint(application.raw_row_hash, normalized, "dimension_scoring:example")
    # Compare consumed facts with unchanged source identity, not a new submission.
    changed = deepcopy(normalized)
    changed["child_details"][0]["birth_date"] = "2016-07-01"
    assert input_fingerprint(application.raw_row_hash, changed, "screening") == screen
    assert input_fingerprint(application.raw_row_hash, changed, "dimension_scoring:example") == score
    changed["child_details"][0]["first_name"] = "Different"
    assert input_fingerprint(application.raw_row_hash, changed, "screening") != screen
    assert input_fingerprint(application.raw_row_hash, changed, "dimension_scoring:example") == score
    changed["child_details"][0]["age"] = 10
    assert input_fingerprint(application.raw_row_hash, changed, "dimension_scoring:example") != score


def test_missing_ages_stay_unknown_and_essays_are_not_redacted():
    application = household()
    application.normalized = {"child_details": [{"first_name": "Casey"}]}
    application.raw_row["essays"]["household_introduction"] = "Avery and Casey enjoy shared gardening."
    screen = block(screening.build_prompt(application), "fields")
    scored = block(dimension_scoring.build_prompt(application, a_pattern_report().dimensions), "applicant")
    assert screen["applicant_age"] is None
    assert screen["co_applicant_age"] is None
    assert screen["child_details"] == [{"first_name": "Casey"}]
    assert scored["facts"]["child_details"] == [{}]
    assert any("Avery and Casey" in essay["answer"] for essay in scored["essays"])
