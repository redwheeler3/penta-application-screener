"""Parse the exported vacancy-list response sheet without guessing through conflicts."""

import csv
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.core.text import normalize_email
from app.core.time import PACIFIC

EMAIL = TypeAdapter(EmailStr)


@dataclass(frozen=True)
class ImportedVacancySubscription:
    email: str
    unit_sizes: frozenset[int]
    consented_at: datetime
    row_number: int


@dataclass(frozen=True)
class VacancyImportResult:
    subscriptions: tuple[ImportedVacancySubscription, ...]
    errors: tuple[str, ...]


def parse_vacancy_csv(
    path: Path,
    *,
    email_column: str = "Email Address",
    preferences_column: str = "Please notify me when a unit of the following size is available",
    timestamp_column: str = "Timestamp",
) -> VacancyImportResult:
    subscriptions = []
    errors = []
    seen: dict[str, int] = {}
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = csv.DictReader(source)
        missing = {
            email_column,
            preferences_column,
            timestamp_column,
        } - set(rows.fieldnames or ())
        if missing:
            return VacancyImportResult(
                subscriptions=(),
                errors=(f"Missing columns: {', '.join(sorted(missing))}",),
            )
        for row_number, row in enumerate(rows, start=2):
            email = normalize_email(row.get(email_column) or "")
            try:
                EMAIL.validate_python(email)
            except ValidationError:
                errors.append(f"Row {row_number}: invalid email address")
                continue
            previous = seen.get(email)
            if previous is not None:
                errors.append(
                    f"Rows {previous} and {row_number}: normalized email collision for {email}"
                )
                continue
            seen[email] = row_number
            sizes = _unit_sizes(row.get(preferences_column) or "")
            if not sizes:
                errors.append(f"Row {row_number}: no recognized unit size")
                continue
            try:
                consented_at = _timestamp(row.get(timestamp_column) or "")
            except ValueError:
                errors.append(f"Row {row_number}: invalid consent timestamp")
                continue
            subscriptions.append(
                ImportedVacancySubscription(
                    email=email,
                    unit_sizes=frozenset(sizes),
                    consented_at=consented_at,
                    row_number=row_number,
                )
            )
    return VacancyImportResult(
        subscriptions=tuple(subscriptions),
        errors=tuple(errors),
    )


def _unit_sizes(value: str) -> set[int]:
    normalized = value.casefold()
    return {
        size
        for size in (1, 2, 3)
        if re.search(rf"\b{size}\s*bed(?:room)?s?\b", normalized)
    }


def _timestamp(value: str) -> datetime:
    raw = value.strip()
    parsed = None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        for pattern in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
            try:
                parsed = datetime.strptime(raw, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError("invalid timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=PACIFIC)
    return parsed.astimezone(UTC)
