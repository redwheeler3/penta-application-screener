"""Pure intake-copy operations shared by the future applicant API and retention jobs."""

import hashlib
import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationVersion,
    Opening,
)
from app.domain.ages import age_on
from app.schemas.intake import CanonicalApplicationAnswers, WorkingApplicationAnswers
from app.services.opening_participation import apply_opening_selection


def stored_answers(answers: BaseModel) -> dict[str, Any]:
    return answers.model_dump(mode="json")


def canonical_answers(answers: CanonicalApplicationAnswers) -> dict[str, Any]:
    return stored_answers(answers)


def content_hash(answers: dict[str, Any]) -> str:
    serialized = json.dumps(answers, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def save_working_copy(
    application: Application,
    answers: BaseModel,
    *,
    saved_at: datetime,
    opening_ids: list[int] | None = None,
) -> None:
    stored = stored_answers(answers)
    application.working_answers = stored
    application.working_content_hash = content_hash(stored)
    application.working_saved_at = saved_at
    if opening_ids is not None:
        application.working_opening_ids = list(opening_ids)
    application.working_revision = (application.working_revision or 0) + 1


def create_application(
    db: Session,
    primary_email: str,
    answers: WorkingApplicationAnswers | CanonicalApplicationAnswers,
    *,
    saved_at: datetime,
    opening_ids: list[int] | None = None,
) -> Application:
    application = Application(
        primary_email=primary_email,
        applicant_name=_full_name(answers.applicant.first_name, answers.applicant.last_name),
        co_applicant_name=(
            _full_name(answers.co_applicant.first_name, answers.co_applicant.last_name)
            if answers.co_applicant is not None
            else None
        ),
        raw_row={},
        raw_row_hash=content_hash({}),
        normalized={},
    )
    db.add(application)
    save_working_copy(
        application,
        answers,
        saved_at=saved_at,
        opening_ids=opening_ids,
    )
    db.flush()
    return application


def publish_working_copy(
    db: Session,
    application: Application,
    answers: CanonicalApplicationAnswers,
    openings: list[Opening],
    *,
    submitted_at: datetime,
) -> None:
    """Atomically replace the committee projection and selected opening participation."""
    selected_opening_ids = [opening.id for opening in openings]
    save_working_copy(
        application,
        answers,
        saved_at=submitted_at,
        opening_ids=selected_opening_ids,
    )
    stored = stored_answers(answers)
    application.primary_email = str(answers.applicant.email).lower()
    application.applicant_name = _full_name(
        answers.applicant.first_name, answers.applicant.last_name
    )
    application.co_applicant_name = (
        _full_name(answers.co_applicant.first_name, answers.co_applicant.last_name)
        if answers.co_applicant is not None
        else None
    )
    application.raw_row = stored
    application.raw_row_hash = content_hash(stored)
    application.normalized = normalize_answers(
        answers,
        as_of_date=pacific_today(now=submitted_at),
    )
    application.submitted_at = submitted_at
    application.declaration_accepted_at = submitted_at
    db.add(
        ApplicationVersion(
            application_id=application.id,
            answers=stored,
            normalized=application.normalized,
            selected_opening_ids=selected_opening_ids,
            content_hash=application.raw_row_hash,
            submitted_at=submitted_at,
            declaration_accepted_at=submitted_at,
        )
    )

    apply_opening_selection(
        db,
        application,
        openings,
        submitted_at=submitted_at,
    )


def normalize_answers(
    answers: CanonicalApplicationAnswers,
    *,
    as_of_date: date,
) -> dict[str, Any]:
    co_applicant = answers.co_applicant
    co_employment = answers.co_applicant_employment if co_applicant is not None else None
    return {
        "applicant_name": _full_name(
            answers.applicant.first_name, answers.applicant.last_name
        ),
        "co_applicant_name": (
            _full_name(co_applicant.first_name, co_applicant.last_name)
            if co_applicant is not None
            else None
        ),
        "applicant_age": age_on(answers.applicant.birth_date, as_of_date),
        "applicant_birth_date": answers.applicant.birth_date.isoformat(),
        "co_applicant_age": (
            age_on(co_applicant.birth_date, as_of_date)
            if co_applicant is not None
            else None
        ),
        "co_applicant_birth_date": (
            co_applicant.birth_date.isoformat() if co_applicant is not None else None
        ),
        "adult_count": 1 + int(co_applicant is not None),
        "child_count": len(answers.children),
        "child_details": [
            {
                "first_name": child.first_name,
                "last_name": child.last_name,
                "age": age_on(child.birth_date, as_of_date),
                "birth_date": child.birth_date.isoformat(),
            }
            for child in answers.children
        ],
        "household_income": answers.household_income,
        "applicant_income": answers.applicant_income,
        "co_applicant_income": (
            answers.co_applicant_income if co_applicant is not None else None
        ),
        "has_real_estate": answers.owns_real_estate,
        "pets_text": answers.pets,
        "household_photo_link": (
            str(answers.household_photo_link) if answers.household_photo_link is not None else None
        ),
        "applicant_email": str(answers.applicant.email),
        "co_applicant_email": str(co_applicant.email) if co_applicant is not None else None,
        "co_applicant_phone": co_applicant.phone if co_applicant is not None else None,
        "applicant_employment_status": answers.applicant_employment.status.value,
        "co_applicant_employment_status": (
            co_employment.status.value if co_employment is not None else None
        ),
        "applicant_employment_start": (
            answers.applicant_employment.start_date.isoformat()
            if answers.applicant_employment.start_date is not None
            else None
        ),
        "co_applicant_employment_start": (
            co_employment.start_date.isoformat()
            if co_employment is not None and co_employment.start_date is not None
            else None
        ),
    }


def _full_name(first_name: str, last_name: str) -> str:
    return " ".join((first_name.strip(), last_name.strip()))
