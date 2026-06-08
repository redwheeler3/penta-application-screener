from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GoogleCredential


def save_google_token(db: Session, *, user_id: int, token: dict) -> GoogleCredential:
    credential = db.scalar(select(GoogleCredential).where(GoogleCredential.user_id == user_id))

    if credential is None:
        credential = GoogleCredential(user_id=user_id, token=token)
        db.add(credential)
    else:
        credential.token = token

    db.commit()
    db.refresh(credential)
    return credential


def get_google_token(db: Session, *, user_id: int) -> dict | None:
    credential = db.scalar(select(GoogleCredential).where(GoogleCredential.user_id == user_id))
    if credential is None:
        return None
    return credential.token

