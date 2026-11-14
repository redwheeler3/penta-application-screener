"""Prepare a vacancy before exercising its direct-selection boundary."""
from app.schemas.openings import OpeningCreate
from app.services.openings.catalog import create_opening
from app.services.openings.direct_selection import select_previous_applicant


def create_direct_selection_opening(db, application_id, *, move_in_date, decided_by, now=None):
    opening = create_opening(db, OpeningCreate(
        unitSizeBedrooms=2,
        housingChargeCents=100000,
        applicationCloseDate=move_in_date, moveInDate=move_in_date), now=now)
    return select_previous_applicant(db, opening, application_id, decided_by=decided_by, now=now)


def create_published_opening(db, values, **kwargs):
    from app.services.openings.catalog import publish_opening
    opening = create_opening(db, values, **kwargs)
    publish_opening(db, opening, now=kwargs.get("now"))
    return opening
