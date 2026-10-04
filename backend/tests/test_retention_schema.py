"""Schema-level ownership rules that keep complete applicant deletion complete."""

from app.db.models import Base

APPLICATION_OWNED_FOREIGN_KEYS = {
    ("application_participations", "application_id", "applications"),
    ("application_versions", "application_id", "applications"),
    ("applicant_drafts", "application_id", "applications"),
    ("magic_link_tokens", "application_id", "applications"),
    ("magic_link_tokens", "applicant_draft_id", "applicant_drafts"),
    ("browser_sessions", "application_id", "applications"),
    ("email_deliveries", "application_id", "applications"),
    ("email_deliveries", "magic_link_token_id", "magic_link_tokens"),
    ("email_deliveries", "applicant_draft_id", "applicant_drafts"),
    ("member_eligibility", "application_id", "applications"),
    ("application_notes", "application_id", "applications"),
    ("application_committee_notes", "application_id", "applications"),
    ("application_stars", "application_id", "applications"),
    ("application_shortlist", "application_id", "applications"),
    ("application_ai_results", "application_id", "applications"),
    ("application_ai_selections", "application_id", "applications"),
}


def test_every_application_owned_foreign_key_cascades() -> None:
    actual = {
        (table.name, foreign_key.parent.name, foreign_key.column.table.name)
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
        if foreign_key.column.table.name
        in {"applications", "applicant_drafts", "magic_link_tokens"}
        and foreign_key.parent.name != "reconciliation_draft_id"
    }

    assert actual == APPLICATION_OWNED_FOREIGN_KEYS
    for table_name, column_name, _ in actual:
        column = Base.metadata.tables[table_name].columns[column_name]
        foreign_key = next(iter(column.foreign_keys))
        assert foreign_key.ondelete == "CASCADE"


def test_comparison_copy_does_not_own_the_authenticated_session() -> None:
    column = Base.metadata.tables["browser_sessions"].columns["reconciliation_draft_id"]
    assert column.nullable is True
    assert next(iter(column.foreign_keys)).ondelete == "SET NULL"
