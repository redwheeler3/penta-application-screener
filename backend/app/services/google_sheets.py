from collections.abc import Iterable
from typing import Any

import httplib2
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

from app.core.config import Settings
from app.core.google_oauth import load_google_client_config

GOOGLE_HTTP_TIMEOUT_SECONDS = 10


def google_auth_request_with_timeout(*args, **kwargs):
    """Make an OAuth request without letting an unavailable Google endpoint hang a web request."""
    kwargs["timeout"] = GOOGLE_HTTP_TIMEOUT_SECONDS
    return GoogleAuthRequest()(*args, **kwargs)


def sheets_service(credentials: Credentials):
    """Build a Sheets client whose network calls have a firm deadline."""
    http = AuthorizedHttp(
        credentials,
        http=httplib2.Http(timeout=GOOGLE_HTTP_TIMEOUT_SECONDS),
    )
    return build("sheets", "v4", http=http, cache_discovery=False)


def credentials_from_token(token: dict[str, Any], settings: Settings) -> Credentials:
    client_config = load_google_client_config(settings)
    # Use the scopes the token was ACTUALLY granted (its own 'scope' field), not the app's
    # login-scope constant. Post-M18 the login scope is identity-only, but a sheet-reader
    # token also carries drive.file — hardcoding the login scopes here understated the grant
    # and would make a refresh request the wrong (narrower) scope set. Fall back to the login
    # scopes only when the token has no scope recorded.
    granted = token.get("scope")
    scopes = granted.split() if granted else settings.google_oauth_scopes.split()
    credentials = Credentials(
        token=token.get("access_token"),
        refresh_token=token.get("refresh_token"),
        token_uri=client_config["token_uri"],
        client_id=client_config["client_id"],
        client_secret=client_config["client_secret"],
        scopes=scopes,
    )

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(google_auth_request_with_timeout)

    return credentials


def fetch_sheet_rows(*, sheet_id: str, token: dict[str, Any], settings: Settings) -> list[dict[str, Any]]:
    credentials = credentials_from_token(token, settings)
    service = sheets_service(credentials)
    metadata = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    sheets = metadata.get("sheets", [])
    if not sheets:
        return []

    first_sheet_title = sheets[0]["properties"]["title"]
    values = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=first_sheet_title)
        .execute()
        .get("values", [])
    )
    if not values:
        return []

    headers = make_unique_headers(str(header).strip() for header in values[0])
    rows: list[dict[str, Any]] = []
    for index, row_values in enumerate(values[1:], start=2):
        row = {header: row_values[position] if position < len(row_values) else "" for position, header in enumerate(headers)}
        row["_source_row_number"] = index
        rows.append(row)

    return rows


def fetch_sheet_title(*, sheet_id: str, token: dict[str, Any], settings: Settings) -> str | None:
    credentials = credentials_from_token(token, settings)
    service = sheets_service(credentials)
    metadata = service.spreadsheets().get(spreadsheetId=sheet_id, fields="properties/title").execute()
    title = metadata.get("properties", {}).get("title")
    if not title:
        return None
    return str(title)


def make_unique_headers(headers: Iterable[str]) -> list[str]:
    counts: dict[str, int] = {}
    unique_headers: list[str] = []

    for header in headers:
        normalized_header = str(header).strip()
        if not normalized_header:
            normalized_header = "Unnamed column"

        counts[normalized_header] = counts.get(normalized_header, 0) + 1
        if counts[normalized_header] == 1:
            unique_headers.append(normalized_header)
        else:
            unique_headers.append(f"{normalized_header} [{counts[normalized_header]}]")

    return unique_headers
