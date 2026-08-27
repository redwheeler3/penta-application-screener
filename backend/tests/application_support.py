from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import pacific_today
from app.db.models import Application, ApplicationParticipation, Opening


def activate_application(db: Session, application: Application) -> Application:
    """Attach a submitted test application to the shared current opening."""
    today = pacific_today()
    opening = db.scalar(
        select(Opening)
        .where(
            Opening.published_at.is_not(None),
            Opening.move_in_date > today,
        )
        .order_by(Opening.id)
        .limit(1)
    )
    if opening is None:
        opening = Opening(
            unit_size_bedrooms=2,
            housing_charge_cents=100_000,
            application_open_date=today - timedelta(days=1),
            application_close_date=today + timedelta(days=10),
            move_in_date=today + timedelta(days=30),
            published_at=datetime.now(UTC),
        )
        db.add(opening)
    db.add(application)
    db.flush()
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=opening.id,
            applied_at=application.submitted_at or datetime.now(UTC),
        )
    )
    db.commit()
    return application
