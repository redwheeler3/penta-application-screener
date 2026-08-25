from datetime import UTC
from pathlib import Path

import pytest

from app.services.synthetic_fixture import read_synthetic_fixture

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "test-data"
    / "synthetic-penta-application-responses.csv"
)


def test_every_synthetic_row_matches_the_canonical_application_schema() -> None:
    records = list(read_synthetic_fixture(FIXTURE))

    assert len(records) == 100
    assert len({str(record.answers.applicant.email) for record in records}) == 100
    assert all(record.submitted_at.tzinfo == UTC for record in records)


def test_fixture_reader_rejects_ambiguous_booleans(tmp_path) -> None:
    header, row = FIXTURE.read_text(encoding="utf-8").splitlines()[:2]
    broken = row.replace(",false,false,false,", ",maybe,false,false,", 1)
    fixture = tmp_path / "invalid.csv"
    fixture.write_text(f"{header}\n{broken}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be 'true' or 'false'"):
        list(read_synthetic_fixture(fixture))
