from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.time import pacific_today
from app.db.models import Application, ApplicationParticipation, Base, Opening
from app.services.application_scope import committee_applications


def test_committee_scope_contains_only_active_submissions() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    submitted_at = datetime(2026, 1, 1, tzinfo=UTC)
    today = pacific_today()
    current_opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=100_000,
        application_open_date=today - timedelta(days=10),
        application_close_date=today + timedelta(days=10),
        move_in_date=today + timedelta(days=30),
        published_at=submitted_at,
    )
    archived_opening = Opening(
        unit_size_bedrooms=1,
        housing_charge_cents=90_000,
        application_open_date=today - timedelta(days=60),
        application_close_date=today - timedelta(days=40),
        move_in_date=today - timedelta(days=1),
        published_at=submitted_at,
    )
    applications = [
        Application(
                primary_email="draft@example.com",
                applicant_name="Draft",
                raw_row={},
                raw_row_hash="draft",
                normalized={},
        ),
        Application(
                primary_email="submitted@example.com",
                applicant_name="Submitted",
                raw_row={},
                raw_row_hash="submitted",
                normalized={},
                submitted_at=submitted_at,
        ),
        Application(
                primary_email="archived@example.com",
                applicant_name="Archived",
                raw_row={},
                raw_row_hash="archived",
                normalized={},
                submitted_at=submitted_at,
        ),
        Application(
                primary_email="withdrawn@example.com",
                applicant_name="Withdrawn",
                raw_row={},
                raw_row_hash="withdrawn",
                normalized={},
                submitted_at=submitted_at,
        ),
        Application(
                primary_email="deleted@example.com",
                applicant_name="Deleted",
                raw_row={},
                raw_row_hash="deleted",
                normalized={},
                submitted_at=submitted_at,
                deleted_at=submitted_at,
        ),
    ]
    db.add_all([current_opening, archived_opening, *applications])
    db.flush()
    db.add_all(
        [
            ApplicationParticipation(
                application_id=applications[1].id,
                opening_id=current_opening.id,
                applied_at=submitted_at,
            ),
            ApplicationParticipation(
                application_id=applications[2].id,
                opening_id=archived_opening.id,
                applied_at=submitted_at,
            ),
            ApplicationParticipation(
                application_id=applications[3].id,
                opening_id=current_opening.id,
                applied_at=submitted_at,
                withdrawn_at=submitted_at,
            ),
            ApplicationParticipation(
                application_id=applications[4].id,
                opening_id=current_opening.id,
                applied_at=submitted_at,
            ),
        ]
    )
    db.commit()

    assert [application.primary_email for application in committee_applications(db)] == [
        "submitted@example.com"
    ]
