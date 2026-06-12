from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.db.models import Application, HardFilterStatus, User
from app.db.session import get_db
from app.services.settings import get_app_settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def read_dashboard(
    _: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_app_settings(db)
    total = db.scalar(select(func.count()).select_from(Application)) or 0
    eligible = count_by_status(db, HardFilterStatus.ELIGIBLE)
    filtered_out = count_by_status(db, HardFilterStatus.FILTERED_OUT)

    return {
        "settingsComplete": bool(settings.google_sheet_id),
        "counts": {
            "submitted": total,
            "eligible": eligible,
            "filteredOut": filtered_out,
        },
    }


def count_by_status(db: Session, status: HardFilterStatus) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.hard_filter_status == status)
        )
        or 0
    )

