from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/penta_screener.db"
    session_secret: str = "dev-only-change-me"
    frontend_url: str = "http://localhost:5173"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_oauth_client_secrets_file: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    # Request the canonical scope URIs for email/profile, not the short aliases.
    # Google grants these but echoes them back as the full userinfo.* URIs, so
    # requesting the aliases makes Authlib's literal scope check report them as
    # "missing" even though they were granted.
    google_oauth_scopes: str = (
        "openid "
        "https://www.googleapis.com/auth/userinfo.email "
        "https://www.googleapis.com/auth/userinfo.profile "
        "https://www.googleapis.com/auth/spreadsheets.readonly "
        "https://www.googleapis.com/auth/documents "
        "https://www.googleapis.com/auth/drive.file"
    )

    model_config = SettingsConfigDict(
        env_file=("../.env", "../.env.local", ".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.google_oauth_client_secrets_file:
        secrets_dir = Path(__file__).resolve().parents[2] / "secrets"
        matches = sorted(secrets_dir.glob("client_secret_*.json"))
        if matches:
            settings.google_oauth_client_secrets_file = str(matches[0])
    return settings


def resolve_backend_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parents[2] / candidate
