from app.api.sync import format_sync_error_detail


def test_format_sync_error_detail_expands_hard_filter_enum_values() -> None:
    detail = format_sync_error_detail(
        "Import failed after reading 92 rows",
        LookupError(
            "'needs_review' is not among the defined enum values. "
            "Enum name: hardfilterstatus. Possible values: eligible, filtered_ou.."
        ),
    )

    assert "filtered_ou.." not in detail
    assert "Allowed hard filter statuses: eligible, filtered_out" in detail
    assert "older schema" in detail
