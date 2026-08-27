"""Read committee-facing content from stored application answers.

Built-in applications use a nested essay schema; retained imported rows use their original
question headings. This reader supports both stored shapes without mutating source data.
"""

from typing import Any

LEGACY_ESSAY_FIELDS: tuple[tuple[str, str], ...] = (
    (
        "About the household",
        "Please introduce yourself and your family, including your employment background, interests, and values.",
    ),
    (
        "Skills to contribute",
        "Please tell us about any skills you and the co-applicant could actively contribute to the running and maintenance of the co-op.",
    ),
    (
        "Previous co-op experience",
        "Please tell us about any previous co-op experience you or the co-applicant may have.",
    ),
    (
        "Why a co-op",
        "Describe why you want to live in a co-op and in what ways you would be a valuable member to the co-op.",
    ),
)

BUILT_IN_ESSAY_FIELDS: tuple[tuple[str, str], ...] = (
    ("About the household", "household_introduction"),
    ("Skills to contribute", "skills_to_contribute"),
    ("Previous co-op experience", "previous_coop_experience"),
    ("Why a co-op", "why_coop"),
    ("Additional information", "additional_information"),
)


def extract_essays(answers: dict[str, Any]) -> list[dict[str, str]]:
    """Return essay answers in form order from either retained or built-in data."""
    built_in = answers.get("essays")
    if isinstance(built_in, dict):
        return [
            {
                "label": label,
                "question": label,
                "answer": str(built_in.get(key, "") or "").strip(),
            }
            for label, key in BUILT_IN_ESSAY_FIELDS
        ]

    return [
        {
            "label": label,
            "question": question,
            "answer": str(answers.get(question, "") or "").strip(),
        }
        for label, question in LEGACY_ESSAY_FIELDS
    ]
