from collections.abc import Iterable
from typing import Any

import httplib2
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

from app.services.google_credentials import GOOGLE_HTTP_TIMEOUT_SECONDS
from app.services.google_retry import retry_google_request


def sheets_service(credentials: Credentials):
    """Build a Sheets client whose network calls have a firm deadline."""
    http = AuthorizedHttp(
        credentials,
        http=httplib2.Http(timeout=GOOGLE_HTTP_TIMEOUT_SECONDS),
    )
    return build("sheets", "v4", http=http, cache_discovery=False)


def fetch_sheet_rows(*, sheet_id: str, credentials: Credentials) -> list[dict[str, Any]]:
    service = sheets_service(credentials)
    metadata = retry_google_request(
        lambda: service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    )
    sheets = metadata.get("sheets", [])
    if not sheets:
        return []

    first_sheet_title = sheets[0]["properties"]["title"]
    values_response = retry_google_request(
        lambda: service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=first_sheet_title)
        .execute()
    )
    values = values_response.get("values", [])
    if not values:
        return []

    headers = make_unique_headers(str(header).strip() for header in values[0])
    rows: list[dict[str, Any]] = []
    for index, row_values in enumerate(values[1:], start=2):
        row = {header: row_values[position] if position < len(row_values) else "" for position, header in enumerate(headers)}
        row["_source_row_number"] = index
        rows.append(row)

    return rows


def fetch_sheet_title(*, sheet_id: str, credentials: Credentials) -> str | None:
    service = sheets_service(credentials)
    metadata = retry_google_request(
        lambda: service.spreadsheets()
        .get(spreadsheetId=sheet_id, fields="properties/title")
        .execute()
    )
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
