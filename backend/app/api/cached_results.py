"""Background reuse of existing AI results; this endpoint never generates output."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.base import ResponseModel
from app.services.applications.scope import resolve_visible_opening_id
from app.services.cached_results import refresh_cached_results

router = APIRouter(prefix="/cached-results", tags=["cached-results"])


class CachedResultsResponse(ResponseModel):
    changed: bool


@router.post("/refresh", response_model=CachedResultsResponse)
def refresh(opening_id: int, user: User = Depends(require_current_user), db: Session = Depends(get_db)):
    opening_id = resolve_visible_opening_id(db, opening_id)
    return CachedResultsResponse(changed=refresh_cached_results(db, opening_id))
