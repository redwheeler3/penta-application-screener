from app.db.models import ApplicationStatus, MemberEligibility, StatusSource
from app.domain.status import (
    effective_status,
    findings_fingerprint,
    override_is_stale,
    resolve_machine_status,
)


def make_override(**kwargs) -> MemberEligibility:
    defaults = {
        "application_id": 1,
        "user_id": 1,
        "status": ApplicationStatus.ELIGIBLE,
        "reviewed_fingerprint": None,
    }
    defaults.update(kwargs)
    return MemberEligibility(**defaults)


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


def test_effective_status_uses_override_when_present() -> None:
    # A member's override wins over the machine verdict (here: rules-ineligible), and its
    # source is always HUMAN.
    override = make_override(status=ApplicationStatus.ELIGIBLE)
    assert effective_status(override, has_reasons=True, has_ai_flags=False) == (
        ApplicationStatus.ELIGIBLE,
        StatusSource.HUMAN,
    )


def test_effective_status_falls_back_to_machine_without_override() -> None:
    assert effective_status(None, has_reasons=True, has_ai_flags=False) == (
        ApplicationStatus.INELIGIBLE,
        StatusSource.RULES,
    )


def test_staleness_only_for_changed_findings() -> None:
    flags = [{"category": "pet_policy"}]
    override = make_override(reviewed_fingerprint=findings_fingerprint([], flags))
    # Same findings -> not stale.
    assert override_is_stale(override, [], flags) is False
    # New finding -> stale.
    assert override_is_stale(override, [], [*flags, {"category": "fake_contact"}]) is True


def test_no_override_is_never_stale() -> None:
    # An absent override (machine-owned view) always reflects the current findings.
    assert override_is_stale(None, [], [{"category": "pet_policy"}]) is False
