"""Admin-only opening configuration and lifecycle endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_recent_admin
from app.api.problems import Problem
from app.db.models import Opening, User
from app.db.session import get_db
from app.schemas.openings import OpeningOut, OpeningsResponse, OpeningWrite
from app.services.openings import (
    create_opening,
    list_openings,
    opening_phase,
    publish_opening,
    update_opening,
)
from app.services.passwordless_auth import as_utc

router = APIRouter(prefix="/openings", tags=["openings"])


def _opening(db: Session, opening_id: int) -> Opening:
    opening = db.get(Opening, opening_id)
    if opening is None:
        raise Problem("not_found", detail="Opening not found.")
    return opening


def _response(db: Session) -> OpeningsResponse:
    return OpeningsResponse(
        openings=[
            OpeningOut(
                id=opening.id,
                unit_size_bedrooms=opening.unit_size_bedrooms,
                housing_charge_cents=opening.housing_charge_cents,
                application_open_date=opening.application_open_date,
                application_close_date=opening.application_close_date,
                move_in_date=opening.move_in_date,
                phase=opening_phase(opening),
                published_at=(
                    as_utc(opening.published_at) if opening.published_at is not None else None
                ),
                submission_count=submission_count,
                created_at=as_utc(opening.created_at),
                updated_at=as_utc(opening.updated_at),
            )
            for opening, submission_count in list_openings(db)
        ]
    )


@router.get("", response_model=OpeningsResponse)
def read_openings(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningsResponse:
    return _response(db)


@router.post("", response_model=OpeningsResponse)
def add_opening(
    body: OpeningWrite,
    _admin: User = Depends(require_recent_admin),
    db: Session = Depends(get_db),
) -> OpeningsResponse:
    create_opening(db, body)
    return _response(db)


@router.put("/{opening_id}", response_model=OpeningsResponse)
def edit_opening(
    opening_id: int,
    body: OpeningWrite,
    _admin: User = Depends(require_recent_admin),
    db: Session = Depends(get_db),
) -> OpeningsResponse:
    update_opening(db, _opening(db, opening_id), body)
    return _response(db)


@router.post("/{opening_id}/publish", response_model=OpeningsResponse)
def publish_draft_opening(
    opening_id: int,
    _admin: User = Depends(require_recent_admin),
    db: Session = Depends(get_db),
) -> OpeningsResponse:
    publish_opening(db, _opening(db, opening_id))
    return _response(db)
