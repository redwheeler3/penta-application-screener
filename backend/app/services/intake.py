"""Pure intake-copy operations shared by the future applicant API and retention jobs."""

import hashlib
import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Application, ApplicationParticipation, Opening
from app.schemas.intake import CanonicalApplicationAnswers, WorkingApplicationAnswers


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
) -> None:
    stored = stored_answers(answers)
    application.working_answers = stored
    application.working_content_hash = content_hash(stored)
    application.working_saved_at = saved_at


def create_application(
    db: Session,
    primary_email: str,
    answers: WorkingApplicationAnswers,
    *,
    saved_at: datetime,
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
    save_working_copy(application, answers, saved_at=saved_at)
    db.flush()
    return application


def publish_working_copy(
    db: Session,
    application: Application,
    answers: CanonicalApplicationAnswers,
    opening: Opening,
    *,
    submitted_at: datetime,
) -> None:
    """Atomically replace the committee projection and enroll in one opening."""
    save_working_copy(application, answers, saved_at=submitted_at)
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
    application.normalized = normalize_answers(answers, move_in_date=opening.move_in_date)
    application.submitted_at = submitted_at
    application.declaration_accepted_at = submitted_at

    participation = db.scalar(
        select(ApplicationParticipation).where(
            ApplicationParticipation.application_id == application.id,
            ApplicationParticipation.opening_id == opening.id,
        )
    )
    if participation is None:
        participation = ApplicationParticipation(
            application_id=application.id,
            opening_id=opening.id,
            submitted_at=submitted_at,
            declaration_accepted_at=submitted_at,
        )
        db.add(participation)
    else:
        participation.submitted_at = submitted_at
        participation.declaration_accepted_at = submitted_at
        participation.retracted_at = None


def normalize_answers(
    answers: CanonicalApplicationAnswers,
    *,
    move_in_date: date,
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
        "applicant_age": _age_on(answers.applicant.birth_date, move_in_date),
        "co_applicant_age": (
            _age_on(co_applicant.birth_date, move_in_date)
            if co_applicant is not None
            else None
        ),
        "adult_count": 1 + int(co_applicant is not None),
        "child_count": len(answers.children),
        "child_details": [
            {
                "first_name": child.first_name,
                "last_name": child.last_name,
                "age": _age_on(child.birth_date, move_in_date),
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


def _age_on(birth_date: date, on_date: date) -> int:
    before_birthday = (on_date.month, on_date.day) < (birth_date.month, birth_date.day)
    return on_date.year - birth_date.year - int(before_birthday)
