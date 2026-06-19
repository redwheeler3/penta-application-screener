import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.core.config import get_settings
from app.db.models import ApplicationStatus, User
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
        raise HTTPException(status_code=400, detail="No Google Sheet configured. Go to Settings and add a Google Sheet link.")

    token = get_google_token(db, user_id=user.id)
    if token is None:
        raise HTTPException(status_code=401, detail="Google credentials expired or missing. Please sign out and sign in again.")

    try:
        rows = fetch_sheet_rows(sheet_id=app_settings.google_sheet_id, token=token, settings=get_settings())
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to read Google Sheet: {type(e).__name__}: {e}",
        ) from e

    if not rows:
        raise HTTPException(status_code=400, detail="Google Sheet returned no data rows. Check that the sheet has a header row and at least one data row.")

    try:
        sync_run = import_applications_from_rows(
            db,
            rows=rows,
            source_sheet_id=app_settings.google_sheet_id,
            settings=app_settings,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=format_sync_error_detail(
                f"Import failed after reading {len(rows)} rows",
                e,
            ),
        ) from e

    return {
        "syncRun": {
            "id": sync_run.id,
            "rowCount": sync_run.row_count,
            "duplicateCount": sync_run.duplicate_count,
            "importedCount": sync_run.imported_count,
            "updatedCount": sync_run.updated_count,
            "unchangedCount": sync_run.unchanged_count,
            "eligibleCount": sync_run.eligible_count,
            "filteredOutCount": sync_run.filtered_out_count,
        }
    }


def format_sync_error_detail(prefix: str, error: Exception) -> str:
    error_message = str(error)
    extra_lines: list[str] = []

    if isinstance(error, LookupError) and "applicationstatus" in error_message.lower():
        error_message = re.sub(r"\. Possible values: .*$", ".", error_message)
        extra_lines.append(
            "Allowed application statuses: "
            + ", ".join(status.value for status in ApplicationStatus)
        )
        extra_lines.append(
            "This usually means the local database contains a row written by an older schema."
        )

    detail = f"{prefix}: {type(error).__name__}: {error_message}"
    if extra_lines:
        detail += "\n" + "\n".join(extra_lines)
    return detail

