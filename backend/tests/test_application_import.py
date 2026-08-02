import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationNote,
    ApplicationStar,
    ApplicationStatus,
    Base,
    MemberEligibility,
)
from app.schemas.settings import AppSettings
from app.services.application_import import (
    extract_essays,
    import_applications_from_rows,
    normalize_application,
    parse_money,
    parse_timestamp,
)
from app.services.google_sheets import make_unique_headers


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_parse_money_handles_common_inputs() -> None:
    assert parse_money("$100,000") == 100_000
    assert parse_money("95k") == 95_000
    assert parse_money("") is None


def test_extract_essays_returns_labeled_answers_in_order() -> None:
    row = {
        "Please introduce yourself and your family, including your employment background, interests, and values.": "We are a family of four.",
        "Please tell us about any skills you and the co-applicant could actively contribute to the running and maintenance of the co-op.": "Carpentry.",
        "Please tell us about any previous co-op experience you or the co-applicant may have.": "",
        "Describe why you want to live in a co-op and in what ways you would be a valuable member to the co-op.": "Community living.",
    }

    essays = extract_essays(row)

    assert [essay["label"] for essay in essays] == [
        "About the household",
        "Skills to contribute",
        "Previous co-op experience",
        "Why a co-op",
    ]
    assert essays[0]["answer"] == "We are a family of four."
    assert essays[2]["answer"] == ""


def test_extract_essays_handles_missing_columns() -> None:
    essays = extract_essays({})
    assert len(essays) == 4
    assert all(essay["answer"] == "" for essay in essays)


def test_normalize_application_extracts_basic_fields() -> None:
    row = {
        "Email Address": "TEST@EXAMPLE.COM",
        "Applicant Name": "Applicant",
        "Co-applicant name": "Co",
        "Number of children under 18 living in the unit on the move-in date": "1",
        "Household gross yearly income": "$100,000",
        "Do you own real estate?": "No",
        "Pets description": "one dog and one cat",
    }

    normalized = normalize_application(row)

    assert normalized["adult_count"] == 2
    assert normalized["child_count"] == 1
    assert normalized["household_income"] == 100_000
    assert normalized["has_real_estate"] is False
    assert normalized["pets_text"] == "one dog and one cat"


def test_make_unique_headers_preserves_repeated_google_form_labels() -> None:
    headers = make_unique_headers(["Email Address", "First name", "First name", "Age", "Age"])

    assert headers == ["Email Address", "First name", "First name [2]", "Age", "Age [2]"]


def test_normalize_application_extracts_real_form_fields() -> None:
    row = {
        "Email Address": "TEST@EXAMPLE.COM",
        "First name": "Applicant",
        "Last name": "Person",
        "First name [2]": "Co",
        "Last name [2]": "Applicant",
        "How many children (under 18) will be living in the unit on the move in date?": "2",
        "Total yearly gross income for your household (add up all the numbers above)": "$100,000",
        "Do you own real estate (land, house, condominium, etc.)?": "No",
        "If you have any pets, please describe them here.": "one dog and one cat",
    }

    normalized = normalize_application(row)

    assert normalized["applicant_name"] == "Applicant Person"
    assert normalized["co_applicant_name"] == "Co Applicant"
    assert normalized["adult_count"] == 2
    assert normalized["child_count"] == 2
    assert normalized["household_income"] == 100_000
    assert normalized["has_real_estate"] is False
    assert normalized["pets_text"] == "one dog and one cat"


def test_normalize_application_derives_household_income_when_total_column_is_absent() -> None:
    normalized = normalize_application(
        {
            "Email Address": "applicant@example.com",
            "Total yearly gross income for applicant": "$55,000",
            "Total yearly gross income for co-applicant": "$45,000",
        }
    )

    assert normalized["applicant_income"] == 55_000
    assert normalized["co_applicant_income"] == 45_000
    assert normalized["household_income"] == 100_000


def test_import_applications_dedupes_by_latest_email_and_upserts() -> None:
    db = make_session()
    rows = [
        {
            "Email Address": "applicant@example.com",
            "Applicant Name": "Old",
            "Number of children under 18 living in the unit on the move-in date": "1",
            "Household gross yearly income": "$100,000",
            "Do you own real estate?": "No",
        },
        {
            "Email Address": "applicant@example.com",
            "Applicant Name": "New",
            "Number of children under 18 living in the unit on the move-in date": "1",
            "Household gross yearly income": "$100,000",
            "Do you own real estate?": "Yes",
        },
    ]

    sync_run = import_applications_from_rows(
        db,
        rows=rows,
        source_sheet_id="sheet-123",
        settings=AppSettings(google_sheet_id="sheet-123"),
    )
    application = db.scalar(select(Application))

    assert sync_run.row_count == 2
    assert sync_run.duplicate_count == 1
    assert sync_run.imported_count == 1
    assert application is not None
    # Last row wins the dedupe (by email), and its normalized data is what's stored. Import
    # does not evaluate eligibility — that's per-member, computed on read — so there is no
    # eligible/filtered count to assert here.
    assert application.applicant_name == "New"
    assert application.normalized["has_real_estate"] is True


def test_dedupe_keeps_latest_by_timestamp_even_when_out_of_sheet_order() -> None:
    # The newer submission appears FIRST in sheet order; only the timestamp says it's newer.
    # Last-in-sheet-wins would wrongly keep "Old" — timestamp comparison keeps "New".
    db = make_session()
    rows = [
        {
            "Timestamp": "06/02/2026 09:00:00",
            "Email Address": "applicant@example.com",
            "Applicant Name": "New",
            "Do you own real estate?": "Yes",
        },
        {
            "Timestamp": "06/01/2026 09:00:00",
            "Email Address": "applicant@example.com",
            "Applicant Name": "Old",
            "Do you own real estate?": "No",
        },
    ]

    sync_run = import_applications_from_rows(
        db, rows=rows, source_sheet_id="s", settings=AppSettings(google_sheet_id="s")
    )
    application = db.scalar(select(Application))

    assert sync_run.duplicate_count == 1
    assert application is not None
    assert application.applicant_name == "New"
    assert application.normalized["has_real_estate"] is True


def test_dedupe_without_timestamps_keeps_last_in_sheet_order() -> None:
    # No Timestamp column → fall back to the prior behaviour: later-in-sheet row wins.
    db = make_session()
    rows = [
        {"Email Address": "a@example.com", "Applicant Name": "First"},
        {"Email Address": "a@example.com", "Applicant Name": "Second"},
    ]

    import_applications_from_rows(
        db, rows=rows, source_sheet_id="s", settings=AppSettings(google_sheet_id="s")
    )
    application = db.scalar(select(Application))

    assert application is not None
    assert application.applicant_name == "Second"


def test_parse_timestamp_handles_google_forms_and_iso() -> None:
    assert parse_timestamp("06/01/2026 09:00:00") is not None
    assert parse_timestamp("06/01/2026 09:00") is not None
    assert parse_timestamp("2026-06-01 09:00:00") is not None
    assert parse_timestamp("") is None
    assert parse_timestamp("not a date") is None
    # A later timestamp compares greater — the property dedup relies on.
    assert parse_timestamp("06/02/2026 09:00:00") > parse_timestamp("06/01/2026 09:00:00")


def test_reimport_of_identical_rows_counts_unchanged_not_updated() -> None:
    db = make_session()
    rows = [
        {
            "Email Address": "a@example.com",
            "Applicant Name": "Avery",
            "Number of children under 18 living in the unit on the move-in date": "1",
            "Household gross yearly income": "$100,000",
            "Do you own real estate?": "No",
        }
    ]
    settings = AppSettings(google_sheet_id="sheet-123")

    first = import_applications_from_rows(db, rows=rows, source_sheet_id="s", settings=settings)
    assert first.imported_count == 1
    assert first.unchanged_count == 0

    application = db.scalar(select(Application))
    updated_at_before = application.updated_at

    # Re-import the byte-identical rows: nothing should be counted as updated.
    second = import_applications_from_rows(db, rows=rows, source_sheet_id="s", settings=settings)
    assert second.imported_count == 0
    assert second.updated_count == 0
    assert second.unchanged_count == 1

    # The row was not rewritten, so its updated_at is untouched.
    db.refresh(application)
    assert application.updated_at == updated_at_before


def test_reimport_with_changed_content_counts_updated() -> None:
    db = make_session()
    base = {
        "Email Address": "a@example.com",
        "Applicant Name": "Avery",
        "Number of children under 18 living in the unit on the move-in date": "1",
        "Household gross yearly income": "$100,000",
        "Do you own real estate?": "No",
    }
    settings = AppSettings(google_sheet_id="sheet-123")
    import_applications_from_rows(db, rows=[base], source_sheet_id="s", settings=settings)

    changed = {**base, "Household gross yearly income": "$120,000"}
    result = import_applications_from_rows(db, rows=[changed], source_sheet_id="s", settings=settings)
    assert result.updated_count == 1
    assert result.unchanged_count == 0


def test_row_deletion_removes_application_and_dependent_data() -> None:
    db = make_session()
    settings = AppSettings(google_sheet_id="sheet-123")
    rows = [
        {"Email Address": "keep@example.com", "Applicant Name": "Keep"},
        {"Email Address": "remove@example.com", "Applicant Name": "Remove"},
    ]
    import_applications_from_rows(db, rows=rows, source_sheet_id="s", settings=settings)
    removed = db.scalar(select(Application).where(Application.primary_email == "remove@example.com"))
    assert removed is not None
    db.add_all([
        ApplicationAIResult(
            application_id=removed.id, kind="screening", cache_key="remove-cache",
            model_id="m", prompt_version="v", output={}
        ),
        ApplicationNote(application_id=removed.id, user_id=1, note="private"),
        ApplicationStar(application_id=removed.id, user_id=1),
        MemberEligibility(application_id=removed.id, user_id=1, status=ApplicationStatus.ELIGIBLE),
    ])
    db.commit()

    result = import_applications_from_rows(
        db, rows=[rows[0]], source_sheet_id="s", settings=settings
    )

    assert result.deleted_count == 1
    assert db.scalar(select(Application).where(Application.primary_email == "remove@example.com")) is None
    assert db.scalar(select(ApplicationAIResult).where(ApplicationAIResult.application_id == removed.id)) is None
    assert db.scalar(select(ApplicationNote).where(ApplicationNote.application_id == removed.id)) is None
    assert db.scalar(select(ApplicationStar).where(ApplicationStar.application_id == removed.id)) is None
    assert db.scalar(select(MemberEligibility).where(MemberEligibility.application_id == removed.id)) is None


def test_shifted_source_row_number_preserves_a_legacy_cache_key() -> None:
    db = make_session()
    settings = AppSettings(google_sheet_id="sheet-123")
    legacy = Application(
        primary_email="a@example.com",
        applicant_name="Avery",
        raw_row={"Email Address": "a@example.com", "Applicant Name": "Avery", "_source_row_number": 7},
        raw_row_hash="legacy-row-number-hash",
        normalized={},
    )
    db.add(legacy)
    db.commit()

    result = import_applications_from_rows(
        db,
        rows=[{"Email Address": "a@example.com", "Applicant Name": "Avery", "_source_row_number": 6}],
        source_sheet_id="s",
        settings=settings,
    )

    db.refresh(legacy)
    assert result.updated_count == 0
    assert result.unchanged_count == 1
    assert legacy.raw_row_hash == "legacy-row-number-hash"


def test_import_rejects_a_sheet_without_usable_emails() -> None:
    db = make_session()

    with pytest.raises(ValueError, match="usable applicant email"):
        import_applications_from_rows(
            db,
            rows=[{"Applicant Name": "No Email"}],
            source_sheet_id="s",
            settings=AppSettings(google_sheet_id="sheet-123"),
        )
