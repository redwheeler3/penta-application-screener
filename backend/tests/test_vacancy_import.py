from datetime import UTC, datetime
from pathlib import Path

from app.services.vacancy_import import parse_vacancy_csv

PREFERENCES = "Please notify me when a unit of the following size is available"


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_import_parses_google_export_and_preserves_consent_time(tmp_path: Path) -> None:
    path = tmp_path / "subscriptions.csv"
    _write(
        path,
        f'Timestamp,Email Address,{PREFERENCES}\n'
        '"7/2/2024 13:45:00",Person@Example.com,"1 bedroom (1 or 2 adults), 3 bedrooms"\n',
    )

    result = parse_vacancy_csv(path)

    assert result.errors == ()
    assert len(result.subscriptions) == 1
    assert result.subscriptions[0].email == "person@example.com"
    assert result.subscriptions[0].unit_sizes == {1, 3}
    assert result.subscriptions[0].consented_at == datetime(2024, 7, 2, 20, 45, tzinfo=UTC)


def test_import_blocks_invalid_rows_and_normalized_collisions(tmp_path: Path) -> None:
    path = tmp_path / "subscriptions.csv"
    _write(
        path,
        f"Timestamp,Email Address,{PREFERENCES}\n"
        '"2026-08-01T12:00:00-07:00",same@example.com,"2 bedroom"\n'
        '"2026-08-02T12:00:00-07:00", SAME@example.com ,"3 bedroom"\n'
        '"bad",invalid,"studio"\n',
    )

    result = parse_vacancy_csv(path)

    assert len(result.subscriptions) == 1
    assert len(result.errors) == 2
    assert "normalized email collision" in result.errors[0]
    assert "invalid email address" in result.errors[1]


def test_import_requires_expected_columns(tmp_path: Path) -> None:
    path = tmp_path / "subscriptions.csv"
    _write(path, "Email Address\nperson@example.com\n")

    result = parse_vacancy_csv(path)

    assert result.subscriptions == ()
    assert result.errors[0].startswith("Missing columns:")
