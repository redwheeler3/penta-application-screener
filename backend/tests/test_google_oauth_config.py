import json

from app.core.config import Settings
from app.core.google_oauth import load_google_client_config


def test_oauth_state_cookie_secure_off_for_local_http_dev() -> None:
    assert Settings(frontend_url="http://localhost:5173").oauth_state_cookie_secure is False


def test_oauth_state_cookie_secure_on_for_https_prod() -> None:
    assert Settings(frontend_url="https://screener.jeffo.net").oauth_state_cookie_secure is True


def test_local_db_backups_default_on_for_dev() -> None:
    # The post-rank auto-snapshot defaults on, so local dev keeps its safety net with no config.
    assert Settings().local_db_backups is True


def test_local_db_backups_can_be_disabled_for_prod() -> None:
    # Prod (fly.toml [env]) sets it off — env is parsed to a real bool, not the string "false".
    assert Settings(local_db_backups=False).local_db_backups is False


def test_login_scopes_are_identity_only_no_drive_or_sheets() -> None:
    # M18 complete: member login grants IDENTITY ONLY — no Drive/Sheets access, so a normal
    # member sees a benign consent screen. Sheet access is the admin's separate drive.file
    # grant (google_sheet_reader_scopes), never at login.
    scopes = Settings().google_oauth_scopes.split()
    assert scopes == [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ]
    assert not any("drive" in s or "spreadsheets" in s for s in scopes), (
        "login must not request any Drive/Sheets scope"
    )


def test_sheet_reader_scopes_add_only_drive_file() -> None:
    # The admin who links the sheet grants this incrementally: identity + drive.file (the
    # least-privilege, Picker-only scope). Never spreadsheets.readonly (all-spreadsheets) or
    # broader drive scopes.
    scopes = Settings().google_sheet_reader_scopes.split()

    assert "https://www.googleapis.com/auth/drive.file" in scopes
    assert "https://www.googleapis.com/auth/spreadsheets.readonly" not in scopes
    assert "https://www.googleapis.com/auth/drive.readonly" not in scopes
    # Still carries identity (the reader is also a logged-in user).
    for identity in (
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ):
        assert identity in scopes


def test_load_google_client_config_from_env_values() -> None:
    settings = Settings(
        google_client_id="client-id",
        google_client_secret="client-secret",
    )

    config = load_google_client_config(settings)

    assert config["client_id"] == "client-id"
    assert config["client_secret"] == "client-secret"
    assert config["auth_uri"] == "https://accounts.google.com/o/oauth2/auth"
    assert config["token_uri"] == "https://oauth2.googleapis.com/token"


def test_load_google_client_config_from_json_file(tmp_path) -> None:
    secrets_file = tmp_path / "google-oauth-client.json"
    secrets_file.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "json-client-id",
                    "client_secret": "json-client-secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        google_client_id="",
        google_client_secret="",
        google_oauth_client_secrets_file=str(secrets_file),
    )

    config = load_google_client_config(settings)

    assert config["client_id"] == "json-client-id"
    assert config["client_secret"] == "json-client-secret"
