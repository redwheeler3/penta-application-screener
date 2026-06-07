from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/penta_screener.db"
    session_secret: str = "dev-only-change-me"
    frontend_url: str = "http://127.0.0.1:5173"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_oauth_client_secrets_file: str = "./secrets/google-oauth-client.json"
    google_redirect_uri: str = "http://127.0.0.1:8000/auth/google/callback"
    google_oauth_scopes: str = (
        "openid email profile "
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
    return Settings()


def resolve_backend_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parents[2] / candidate
