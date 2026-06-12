from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import Application, Base, HardFilterStatus
from app.schemas.settings import AppSettings
from app.services.application_import import import_applications_from_rows, normalize_application, parse_money
from app.services.google_sheets import make_unique_headers


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_parse_money_handles_common_inputs() -> None:
    assert parse_money("$100,000") == 100_000
    assert parse_money("95k") == 95_000
    assert parse_money("") is None


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


def test_import_applications_dedupes_by_latest_email_and_applies_filters() -> None:
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
    assert application.applicant_name == "New"
    assert application.hard_filter_status == HardFilterStatus.FILTERED_OUT
