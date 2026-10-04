"""Load the selected screening result per applicant for status and presentation."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApplicationAIResult, ApplicationAISelection
from app.domain.hard_filters import PetFacts
from app.services.eligibility.rules import pet_facts_from_screening


def selected_screening_results(
    db: Session, application_ids: list[int]
) -> dict[int, ApplicationAIResult]:
    """Return the consumed screening result and its original provenance for each applicant."""
    if not application_ids:
        return {}
    rows = db.execute(select(ApplicationAISelection.application_id, ApplicationAIResult)
        .join(ApplicationAIResult, ApplicationAIResult.id == ApplicationAISelection.result_id)
        .where(ApplicationAISelection.kind == "screening", ApplicationAISelection.application_id.in_(application_ids)))
    return dict(rows.all())


def screening_findings_by_app(
    db: Session, application_ids: list[int]
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, PetFacts]]:
    """Derive flags and pet facts from the same rows in one query.

    Unscreened applicants are absent; a screened applicant with no flags has an empty
    list. Missing pet facts stay unknown rather than falling back to a different result.
    """
    flags = {}
    pets = {}
    for application_id, result in selected_screening_results(db, application_ids).items():
        flags[application_id] = (result.output or {}).get("flags", [])
        facts = pet_facts_from_screening(result.output)
        if facts is not None:
            pets[application_id] = facts
    return flags, pets
