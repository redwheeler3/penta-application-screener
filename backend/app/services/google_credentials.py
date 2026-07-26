import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.google_oauth import load_google_client_config
from app.db.models import GoogleCredential


def exchange_auth_code(*, code: str, settings: Settings) -> dict:
    """Exchange a GIS code-model authorization code for tokens (M18). Returns the token dict
    (access_token + refresh_token + scope + ...), same shape as the login token, so it can be
    stored via save_google_token and read by credentials_from_token.

    ``redirect_uri`` is ``postmessage`` — the value GIS uses for popup (ux_mode:'popup') code
    clients; it MUST match or Google rejects the exchange. The interactive origin of this code
    is what makes a Picker opened with the returned access_token authorize the picked file
    (a server-refreshed token does NOT — see M18 notes)."""
    cfg = load_google_client_config(settings)
    resp = requests.post(
        cfg["token_uri"],
        data={
            "code": code,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": "postmessage",
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


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

