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


def _token_scopes(token: dict) -> set[str]:
    """The scopes a token carries, from its space-delimited ``scope`` field."""
    return set(str(token.get("scope") or "").split())


def save_google_token(db: Session, *, user_id: int, token: dict) -> GoogleCredential:
    """Store a user's Google token — but NEVER downgrade a broader-scoped token to a narrower
    one. This is what keeps the designated sheet-reader working across logins: post-M18 a plain
    login is identity-only, and the stored token's only job is to be an API credential (sync +
    the settings title read use it). If a routine identity-only login overwrote the admin's
    stored ``drive.file`` reader token, sync would then fail with
    ``ACCESS_TOKEN_SCOPE_INSUFFICIENT`` for the whole committee — the reader token is shared.
    So we replace the stored token only when the incoming one is a scope superset; otherwise we
    keep the stored credential (identity is unaffected — that comes from the session, not this
    token). A re-consent that legitimately re-grants ``drive.file`` (the Picker flow, or a login
    that includes it) IS a superset and updates normally, carrying the refresh token forward if
    the new grant omitted it."""
    credential = db.scalar(select(GoogleCredential).where(GoogleCredential.user_id == user_id))

    if credential is None:
        credential = GoogleCredential(user_id=user_id, token=token)
        db.add(credential)
    else:
        stored_scopes = _token_scopes(credential.token)
        incoming_scopes = _token_scopes(token)
        # Only overwrite when the incoming token grants at least everything the stored one did.
        # A narrower (e.g. identity-only) token is discarded — it would strip scopes sync needs.
        if incoming_scopes >= stored_scopes:
            # Preserve the existing refresh token if the new grant didn't return one (Google
            # omits it on re-consent), so durable server-side refresh keeps working.
            if not token.get("refresh_token") and credential.token.get("refresh_token"):
                token = {**token, "refresh_token": credential.token["refresh_token"]}
            credential.token = token

    db.commit()
    db.refresh(credential)
    return credential


def get_google_token(db: Session, *, user_id: int) -> dict | None:
    credential = db.scalar(select(GoogleCredential).where(GoogleCredential.user_id == user_id))
    if credential is None:
        return None
    return credential.token

