import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request

from app.core.config import Settings, get_settings, resolve_backend_path


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    display_name: str
    avatar_url: str | None


async def authorized_google_identity(
    request: Request,
    oauth: OAuth | None = None,
) -> GoogleIdentity | None:
    """Exchange one OIDC callback and return only the identity claims Penta uses."""
    oauth = oauth or get_oauth()
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        if not user_info:
            user_info = await oauth.google.userinfo(token=token)
    except OAuthError:
        return None
    subject = user_info.get("sub")
    email = user_info.get("email")
    if (
        not subject
        or not email
        or user_info.get("email_verified") not in (True, "true")
    ):
        return None
    return GoogleIdentity(
        subject=str(subject),
        email=str(email),
        display_name=str(user_info.get("name") or email),
        avatar_url=(str(user_info["picture"]) if user_info.get("picture") else None),
    )


def load_google_client_config(settings: Settings) -> dict[str, str]:
    if settings.google_client_id and settings.google_client_secret:
        return {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }

    secrets_path = resolve_backend_path(settings.google_oauth_client_secrets_file)
    with secrets_path.open(encoding="utf-8") as file:
        payload: dict[str, Any] = json.load(file)

    web_config = payload.get("web")
    if not isinstance(web_config, dict):
        raise RuntimeError("Google OAuth client secrets file must contain a 'web' object.")

    required_keys = ["client_id", "client_secret", "auth_uri", "token_uri"]
    missing = [key for key in required_keys if not web_config.get(key)]
    if missing:
        raise RuntimeError(f"Google OAuth client secrets file is missing: {', '.join(missing)}")

    return {key: str(web_config[key]) for key in required_keys}


@lru_cache
def get_oauth() -> OAuth:
    settings = get_settings()
    client_config = load_google_client_config(settings)
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=client_config["client_id"],
        client_secret=client_config["client_secret"],
        access_token_url=client_config["token_uri"],
        authorize_url=client_config["auth_uri"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": settings.google_oauth_scopes},
    )
    return oauth
