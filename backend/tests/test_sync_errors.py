from app.api.sync import format_sync_error_detail


def test_format_sync_error_detail_expands_status_enum_values() -> None:
    detail = format_sync_error_detail(
        "Import failed after reading 92 rows",
        LookupError(
            "'needs_review' is not among the defined enum values. "
            "Enum name: applicationstatus. Possible values: eligible, ineligibl.."
        ),
    )

    assert "ineligibl.." not in detail
    assert "Allowed application statuses: eligible, ineligible" in detail
    assert "older schema" in detail
