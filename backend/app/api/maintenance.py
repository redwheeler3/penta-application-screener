"""Explicit, repeatable lifecycle work triggered by an authenticated app session."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.maintenance import MaintenanceResponse
from app.services.email_sender import EmailSender, get_email_sender
from app.services.opening_notifications import send_due_unsuccessful_notices

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.post("/due", response_model=MaintenanceResponse)
def run_due_maintenance(
    _user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> MaintenanceResponse:
    return MaintenanceResponse(
        unsuccessful_notices_sent=send_due_unsuccessful_notices(db, sender)
    )
