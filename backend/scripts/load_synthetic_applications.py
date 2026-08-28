"""Load the committed fictional applications into local openings.

Run from ``backend/`` after creating and publishing an opening:

    python -m scripts.load_synthetic_applications --opening-id 1 --opening-id 2

The loader sends no email. It refuses non-SQLite or non-synthetic runtimes and never
overwrites an existing application that is not already stamped synthetic.
"""

import argparse
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Application, Opening, OpeningPhase
from app.db.session import SessionLocal
from app.services.intake import (
    canonical_answers,
    content_hash,
    create_application,
    publish_working_copy,
)
from app.services.opening_participation import opening_ids_by_application
from app.services.openings import opening_phase
from app.services.synthetic_fixture import read_synthetic_fixture

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "test-data"
    / "synthetic-penta-application-responses.csv"
)


def load_fixture(*, opening_ids: list[int], fixture: Path = DEFAULT_FIXTURE) -> tuple[int, int]:
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        raise RuntimeError("Synthetic applications may be loaded only into SQLite.")
    if not settings.application_data_is_synthetic:
        raise RuntimeError(
            "Set APPLICATION_DATA_IS_SYNTHETIC=true only for a wholly fictional local database."
        )

    db = SessionLocal()
    created = updated = 0
    try:
        if not opening_ids or len(set(opening_ids)) != len(opening_ids):
            raise RuntimeError("Provide one or more distinct opening IDs.")
        openings = [db.get(Opening, opening_id) for opening_id in opening_ids]
        if any(opening is None or opening.published_at is None for opening in openings):
            raise RuntimeError("Every target opening must exist and be published.")
        published_openings = [opening for opening in openings if opening is not None]
        if any(opening_phase(opening) == OpeningPhase.ARCHIVED for opening in published_openings):
            raise RuntimeError("Synthetic applications cannot be loaded into archived openings.")
        target_opening_ids = set(opening_ids)

        for record in read_synthetic_fixture(fixture):
            email = str(record.answers.applicant.email).lower()
            application = db.scalar(
                select(Application).where(
                    Application.primary_email == email,
                    Application.withdrawn_at.is_(None),
                )
            )
            existed = application is not None
            if application is None:
                application = create_application(
                    db,
                    email,
                    record.answers,
                    saved_at=record.submitted_at,
                    opening_ids=opening_ids,
                )
                created += 1
            elif not application.synthetic_data:
                raise RuntimeError(
                    "Refusing to replace an existing application that is not stamped synthetic."
                )

            answers_hash = content_hash(canonical_answers(record.answers))
            current_openings = opening_ids_by_application(db, [application.id])[application.id]
            if (
                application.raw_row_hash == answers_hash
                and set(current_openings) == target_opening_ids
            ):
                application.synthetic_data = True
                continue

            publish_working_copy(
                db,
                application,
                record.answers,
                published_openings,
                submitted_at=record.submitted_at,
            )
            application.synthetic_data = True
            updated += int(existed)

        db.commit()
        return created, updated
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--opening-id",
        type=int,
        action="append",
        required=True,
        dest="opening_ids",
        help="Published opening to apply each record to; repeat for multiple openings.",
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args()

    created, updated = load_fixture(opening_ids=args.opening_ids, fixture=args.fixture)
    print(f"Loaded synthetic applications: {created} created, {updated} updated.")


if __name__ == "__main__":
    main()
