from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.services.application_import import import_applications_from_rows
from app.services.google_credentials import get_google_token
from app.services.google_sheets import fetch_sheet_rows
from app.services.settings import get_app_settings

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/applications")
def sync_applications(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    app_settings = get_app_settings(db)
    if not app_settings.google_sheet_id:
        raise HTTPException(status_code=400, detail="Google Sheet ID is required before syncing applications.")

    token = get_google_token(db, user_id=user.id)
    if token is None:
        raise HTTPException(status_code=401, detail="Google credentials are missing. Please sign in again.")

    rows = fetch_sheet_rows(sheet_id=app_settings.google_sheet_id, token=token, settings=get_settings())
    sync_run = import_applications_from_rows(
        db,
        rows=rows,
        source_sheet_id=app_settings.google_sheet_id,
        settings=app_settings,
    )

    return {
        "syncRun": {
            "id": sync_run.id,
            "rowCount": sync_run.row_count,
            "duplicateCount": sync_run.duplicate_count,
            "importedCount": sync_run.imported_count,
            "updatedCount": sync_run.updated_count,
            "eligibleCount": sync_run.eligible_count,
            "filteredOutCount": sync_run.filtered_out_count,
            "needsReviewCount": sync_run.needs_review_count,
        }
    }

