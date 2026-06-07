import json

from app.core.config import Settings
from app.core.google_oauth import load_google_client_config


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

