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
    # Bootstrap-only: emails seeded onto the access allowlist as admins at startup
    # (one per line, '#' comments). Once seeded, admins manage the list in-app; this
    # file does not revoke. Gitignored — real emails are deployment-specific.
    initial_admins_file: str = "config/initial-admins.txt"
    # Auto-snapshot the SQLite DB after each Rank (VACUUM INTO, into data/backups/). This
    # existed for heavy local iteration — a safety net while the schema/data churned. In the
    # hosted deploy it's redundant (Fly volume snapshots cover durability) and just piles
    # .db files onto the volume, so prod sets this false via fly.toml. Defaults on so local
    # dev is unchanged with no config.
    local_db_backups: bool = True
    # Request the canonical scope URIs for email/profile, not the short aliases.
    # Google grants these but echoes them back as the full userinfo.* URIs, so
    # requesting the aliases makes Authlib's literal scope check report them as
    # "missing" even though they were granted.
    google_oauth_scopes: str = (
        "openid "
        "https://www.googleapis.com/auth/userinfo.email "
        "https://www.googleapis.com/auth/userinfo.profile "
        "https://www.googleapis.com/auth/spreadsheets.readonly"
    )

    model_config = SettingsConfigDict(
        env_file=("../.env", "../.env.local", ".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def secure_cookies(self) -> bool:
        """Mark the session cookie Secure (HTTPS-only) in production. Derived from
        ``frontend_url`` rather than a separate flag: a prod deploy is served over HTTPS
        (``https://screener.jeffo.net``) so cookies must be Secure, while local dev over
        ``http://localhost`` must NOT be (a Secure cookie is dropped on plain HTTP, which
        would silently break the dev login). One source of truth, no flag to forget."""
        return self.frontend_url.startswith("https://")


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
