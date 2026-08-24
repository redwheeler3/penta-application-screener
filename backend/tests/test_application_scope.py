from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Application, Base
from app.services.application_scope import committee_applications


def test_committee_scope_contains_only_active_submissions() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    submitted_at = datetime(2026, 1, 1, tzinfo=UTC)
    db.add_all(
        [
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
                primary_email="deleted@example.com",
                applicant_name="Deleted",
                raw_row={},
                raw_row_hash="deleted",
                normalized={},
                submitted_at=submitted_at,
                deleted_at=submitted_at,
            ),
        ]
    )
    db.commit()

    assert [application.primary_email for application in committee_applications(db)] == [
        "submitted@example.com"
    ]
