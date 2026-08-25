from app.services.application_content import extract_essays
from scripts.harvest_screening_cases import _essays_by_column


def test_extract_essays_reads_built_in_answers_in_form_order() -> None:
    essays = extract_essays(
        {
            "essays": {
                "household_introduction": "Household",
                "skills_to_contribute": "Skills",
                "previous_coop_experience": "Experience",
                "why_coop": "Why",
                "additional_information": "More",
            }
        }
    )

    assert [essay["answer"] for essay in essays] == [
        "Household",
        "Skills",
        "Experience",
        "Why",
        "More",
    ]


def test_extract_essays_keeps_retained_application_questions_readable() -> None:
    question = (
        "Please introduce yourself and your family, including your employment "
        "background, interests, and values."
    )

    essays = extract_essays({question: "A retained answer"})

    assert essays[0]["answer"] == "A retained answer"


def test_screening_harvest_preserves_built_in_essay_shape() -> None:
    essays = {"household_introduction": "Household"}

    assert _essays_by_column({"essays": essays}) == {"essays": essays}


def test_screening_harvest_preserves_retained_question_keys() -> None:
    question = (
        "Please introduce yourself and your family, including your employment "
        "background, interests, and values."
    )

    harvested = _essays_by_column({question: "Household"})

    assert harvested[question] == "Household"
    assert "essays" not in harvested
