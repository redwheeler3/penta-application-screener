import json

from app.core.config import Settings
from app.core.google_oauth import load_google_client_config


def test_secure_cookies_off_for_local_http_dev() -> None:
    # Default (and any http:// frontend) must NOT set Secure — a Secure cookie is dropped
    # over plain HTTP, which would silently break the local dev login.
    assert Settings(frontend_url="http://localhost:5173").secure_cookies is False


def test_secure_cookies_on_for_https_prod() -> None:
    # An https:// frontend (the hosted deploy) flips the session cookie to Secure.
    assert Settings(frontend_url="https://screener.jeffo.net").secure_cookies is True


def test_local_db_backups_default_on_for_dev() -> None:
    # The post-rank auto-snapshot defaults on, so local dev keeps its safety net with no config.
    assert Settings().local_db_backups is True


def test_local_db_backups_can_be_disabled_for_prod() -> None:
    # Prod (fly.toml [env]) sets it off — env is parsed to a real bool, not the string "false".
    assert Settings(local_db_backups=False).local_db_backups is False


def test_login_scopes_current_still_include_sheets_until_picker_lands() -> None:
    # M18 is landing in two coupled steps. Step 1 (this commit) adds the designated-reader
    # plumbing + the drive.file reader scope constant, but LEAVES login scope unchanged —
    # dropping spreadsheets.readonly now would break sync's fallback until the Picker
    # establishes a designated reader. Step 2 (the Picker) drops login to identity-only in
    # the same change. This test guards that coupling: login still carries sheets FOR NOW.
    scopes = Settings().google_oauth_scopes.split()
    assert scopes == [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    ]


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
