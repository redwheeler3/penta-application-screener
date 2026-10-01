"""Load one latest screening result per applicant for status and presentation."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ApplicationAIResult
from app.domain.hard_filters import PetFacts
from app.services.eligibility.rules import pet_facts_from_screening


def latest_screening_results(
    db: Session, application_ids: list[int]
) -> dict[int, ApplicationAIResult]:
    """Return only the newest row for each requested applicant, with ID breaking time ties."""
    if not application_ids:
        return {}
    ordered = (
        select(
            ApplicationAIResult.id,
            func.row_number().over(
                partition_by=ApplicationAIResult.application_id,
                order_by=(ApplicationAIResult.created_at.desc(), ApplicationAIResult.id.desc()),
            ).label("position"),
        )
        .where(
            ApplicationAIResult.kind == "screening",
            ApplicationAIResult.application_id.in_(application_ids),
        )
        .subquery()
    )
    results = db.scalars(
        select(ApplicationAIResult)
        .join(ordered, ordered.c.id == ApplicationAIResult.id)
        .where(ordered.c.position == 1)
    )
    return {result.application_id: result for result in results}


def screening_findings_by_app(
    db: Session, application_ids: list[int]
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, PetFacts]]:
    """Derive flags and pet facts from the same rows in one query.

    Unscreened applicants are absent; a screened applicant with no flags has an empty
    list. Missing pet facts stay unknown rather than falling back to a different result.
    """
    flags = {}
    pets = {}
    for application_id, result in latest_screening_results(db, application_ids).items():
        flags[application_id] = (result.output or {}).get("flags", [])
        facts = pet_facts_from_screening(result.output)
        if facts is not None:
            pets[application_id] = facts
    return flags, pets
