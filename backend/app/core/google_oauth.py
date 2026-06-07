import json
from functools import lru_cache
from typing import Any

from authlib.integrations.starlette_client import OAuth

from app.core.config import Settings, get_settings, resolve_backend_path


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

