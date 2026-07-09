from app.db.models import Application, ApplicationStatus, StatusSource
from app.domain.status import (
    apply_machine_status,
    findings_fingerprint,
    is_stale,
    resolve_machine_status,
)


def make_app(**kwargs) -> Application:
    defaults = {
        "primary_email": "a@x.com",
        "raw_row": {},
        "raw_row_hash": "h",
        "normalized": {},
        "status": ApplicationStatus.ELIGIBLE,
        "status_source": StatusSource.UNTOUCHED,
        "hard_filter_reasons": [],
    }
    defaults.update(kwargs)
    return Application(**defaults)


def test_resolve_rules_take_precedence_over_ai() -> None:
    assert resolve_machine_status(has_reasons=True, has_ai_flags=True) == (
        ApplicationStatus.INELIGIBLE,
        StatusSource.RULES,
    )


def test_resolve_ai_only() -> None:
    assert resolve_machine_status(has_reasons=False, has_ai_flags=True) == (
        ApplicationStatus.INELIGIBLE,
        StatusSource.AI,
    )


def test_resolve_clean_is_untouched() -> None:
    assert resolve_machine_status(has_reasons=False, has_ai_flags=False) == (
        ApplicationStatus.ELIGIBLE,
        StatusSource.UNTOUCHED,
    )


def test_apply_machine_status_does_not_override_human() -> None:
    app = make_app(status=ApplicationStatus.ELIGIBLE, status_source=StatusSource.HUMAN)
    apply_machine_status(app, has_reasons=True, has_ai_flags=False)
    # Human decision is sticky.
    assert app.status == ApplicationStatus.ELIGIBLE
    assert app.status_source == StatusSource.HUMAN


def test_apply_machine_status_sets_rules() -> None:
    app = make_app()
    apply_machine_status(app, has_reasons=True, has_ai_flags=False)
    assert app.status == ApplicationStatus.INELIGIBLE
    assert app.status_source == StatusSource.RULES


def test_staleness_only_for_human_and_changed_findings() -> None:
    flags = [{"category": "pet_policy"}]
    app = make_app(
        status_source=StatusSource.HUMAN,
        reviewed_fingerprint=findings_fingerprint([], flags),
    )
    # Same findings -> not stale.
    assert is_stale(app, flags) is False
    # New finding -> stale.
    assert is_stale(app, [*flags, {"category": "fake_contact"}]) is True


def test_machine_owned_status_is_never_stale() -> None:
    app = make_app(status_source=StatusSource.AI, reviewed_fingerprint=None)
    assert is_stale(app, [{"category": "pet_policy"}]) is False
