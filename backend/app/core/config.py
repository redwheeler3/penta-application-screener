from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/penta_screener.db"
    session_secret: str = "dev-only-change-me"
    frontend_url: str = "http://localhost:5173"
    applicant_frontend_url: str = "http://localhost:5173/?applicant"
    public_website_url: str = "https://www.pentacoop.com"
    public_website_dev_url: str = "http://localhost:8080"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_oauth_client_secrets_file: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    google_applicant_redirect_uri: str = (
        "http://localhost:8000/applicant/auth/google/callback"
    )
    # Eval evidence may be exported only from runs explicitly stamped synthetic.
    # This is false by default so a production or copied database fails closed.
    application_data_is_synthetic: bool = False
    # Direct model-provider credentials. Model/provider choices live in the database;
    # credentials remain deployment secrets and are never returned by the settings API.
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    email_delivery_mode: Literal["capture", "development", "production"] = "capture"
    socketlabs_server_id: str = ""
    socketlabs_injection_api_key: str = ""
    socketlabs_gateway: str = "https://inject-cx.socketlabs.com/api/v1/email"
    socketlabs_api_base: str = "https://api.socketlabs.com"
    magic_link_lifetime_hours: int = 24
    magic_link_request_limit: int = 3
    magic_link_rate_window_minutes: int = 15
    magic_link_coalesce_seconds: int = 60
    session_idle_days: int = 7
    session_absolute_days: int = 30
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
    # Google is identity-only: committee members grant no application-data access.
    # Canonical userinfo.* URIs, not the short aliases: Google echoes
    # the full URIs back, so requesting aliases makes Authlib's literal scope check report them
    # "missing" even when granted.
    google_oauth_scopes: str = (
        "openid "
        "https://www.googleapis.com/auth/userinfo.email "
        "https://www.googleapis.com/auth/userinfo.profile"
    )

    model_config = SettingsConfigDict(
        env_file=("../.env", "../.env.local", ".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def oauth_state_cookie_secure(self) -> bool:
        """Protect the transient Google OAuth-state cookie on an HTTPS frontend."""
        return self.frontend_url.startswith("https://")

    @property
    def email_delivery_enabled(self) -> bool:
        """Whether this runtime is configured to deliver rather than capture email."""
        return self.email_delivery_mode in {"development", "production"}

    def passwordless_cookie_secure(
        self, identity_kind: Literal["applicant", "committee"]
    ) -> bool:
        """Derive each host-only passwordless cookie's Secure flag from its own origin."""
        origin = (
            self.applicant_frontend_url
            if identity_kind == "applicant"
            else self.frontend_url
        )
        return origin.startswith("https://")


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
