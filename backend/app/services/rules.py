"""Resolve copy-on-write member eligibility rules and deterministic filter reasons.

Members without an override use the committee defaults. Eligibility is computed on read;
bulk callers should use ``eligibility_snapshot`` to avoid one query per application.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import pacific_date, pacific_today
from app.db.models import AdminSetting, Application, MemberRules
from app.domain.ages import age_on
from app.domain.hard_filters import (
    PetFacts,
    RulesConfig,
    evaluate_hard_filters,
)
from app.schemas.settings import EligibilityRules

COMMITTEE_DEFAULT_RULES_KEY: Final = "committee_default_rules"


def committee_default_rules(db: Session) -> EligibilityRules:
    """The shared committee-default rules — the baseline every member reads until they
    diverge. Absent row = schema defaults (the DEFAULT_* thresholds)."""
    record = db.scalar(
        select(AdminSetting).where(AdminSetting.key == COMMITTEE_DEFAULT_RULES_KEY)
    )
    if record is None:
        return EligibilityRules()
    return EligibilityRules.model_validate(record.value)


def save_committee_default_rules(db: Session, rules: EligibilityRules) -> EligibilityRules:
    """Upsert the committee-default rules row."""
    record = db.scalar(
        select(AdminSetting).where(AdminSetting.key == COMMITTEE_DEFAULT_RULES_KEY)
    )
    payload = rules.model_dump(mode="json")
    if record is None:
        db.add(AdminSetting(key=COMMITTEE_DEFAULT_RULES_KEY, value=payload))
    else:
        record.value = payload
    db.commit()
    return rules


def member_rules(db: Session, user_id: int) -> tuple[EligibilityRules, bool]:
    """This member's effective rules and whether they are the shared committee default.

    Returns ``(rules, is_default)``: the member's own ``MemberRules`` row if it exists
    (``is_default=False``), else the committee default (``is_default=True``).
    """
    record = db.scalar(select(MemberRules).where(MemberRules.user_id == user_id))
    if record is None:
        return committee_default_rules(db), True
    return EligibilityRules.model_validate(record.rules), False


def save_member_rules(
    db: Session, user_id: int, rules: EligibilityRules
) -> EligibilityRules:
    """Upsert this member's ``MemberRules`` row — the copy-on-write divergence from the
    committee default. After this the member reads their own rules, not the default."""
    record = db.scalar(select(MemberRules).where(MemberRules.user_id == user_id))
    payload = rules.model_dump(mode="json")
    if record is None:
        db.add(MemberRules(user_id=user_id, rules=payload))
    else:
        record.rules = payload
    db.commit()
    return rules


def reset_member_rules(db: Session, user_id: int) -> None:
    """Drop this member's override so they follow the committee default. Idempotent."""
    record = db.scalar(select(MemberRules).where(MemberRules.user_id == user_id))
    if record is not None:
        db.delete(record)
        db.commit()


def rules_config_from(rules: EligibilityRules) -> RulesConfig:
    """Map an ``EligibilityRules`` blob onto the domain ``RulesConfig`` (income_min ->
    min_income, disabled_checks -> tuple). ``today`` keeps its RulesConfig default."""
    return RulesConfig(
        min_income=rules.income_min,
        max_income=rules.income_max,
        min_adult_age=rules.min_adult_age,
        max_child_age=rules.max_child_age,
        min_children=rules.min_children,
        max_children=rules.max_children,
        max_dogs=rules.max_dogs,
        max_cats=rules.max_cats,
        allow_other_pets=rules.allow_other_pets,
        employment_requirement=rules.employment_requirement,
        disabled_checks=tuple(rules.disabled_checks),
        today=pacific_today(),
    )


def rules_config_for(db: Session, user_id: int) -> RulesConfig:
    """The domain ``RulesConfig`` for this member's effective rules — what their
    hard-filter evaluation runs under."""
    return rules_config_from(member_rules(db, user_id)[0])


def committee_default_rules_config(db: Session) -> RulesConfig:
    """The domain ``RulesConfig`` for the shared committee-default ruleset. This is the
    SHARED baseline used by screening and committee-wide eligibility calculations — not any
    one member's rules."""
    return rules_config_from(committee_default_rules(db))


def _reason_to_payload(reason: Any) -> dict[str, Any]:
    """Serialize a ``FilterReason`` for API and eligibility-snapshot consumers."""
    return {"code": reason.code, "message": reason.message, "details": reason.details}


def pet_facts_from_screening(flags_output: dict[str, Any] | None) -> PetFacts | None:
    """The extracted pet inventory from a cached screening result's ``output``, as the
    domain ``PetFacts`` the pet hard filter reads — or ``None`` if the app hasn't been
    screened yet (so the pet check is skipped, exactly as pre-screen callers skip it).

    Pet facts are AI-extracted from the free-text pets field (they can't be derived
    deterministically), so they live on the screening result, not on ``normalized`` — this
    is where the on-read eligibility path lifts them out to feed the per-member pet filter.
    """
    if not flags_output:
        return None
    pets = flags_output.get("pets")
    if not pets:
        return None
    return PetFacts(
        dogs=pets.get("dogs", 0),
        cats=pets.get("cats", 0),
        other_pets=tuple(pets.get("other_pets", []) or ()),
    )


def hard_filter_reasons_for(
    rules_config: RulesConfig,
    application: Application,
    *,
    pet_facts: PetFacts | None = None,
) -> list[dict[str, Any]]:
    """This member's deterministic hard-filter reasons for one applicant, computed on read
    from ``application.normalized`` + a resolved ``RulesConfig``. Same dict shape the removed
    ``hard_filter_reasons`` column stored, so it is a drop-in for the old read.

    Takes an already-resolved ``RulesConfig`` (not a user_id) so callers ranking many apps
    resolve the member's rules once and reuse it across the pool — no per-app DB read.
    ``pet_facts`` (from the app's screening result via ``pet_facts_from_screening``) is passed
    through to ``evaluate_hard_filters`` so the per-member pet limit gates on read; ``None``
    skips the pet check (an unscreened app, or a caller that gates before screening).
    """
    age_date = (
        pacific_date(application.submitted_at)
        if application.submitted_at is not None
        else rules_config.today
    )
    normalized = normalized_with_ages(application.normalized or {}, age_date)
    result = evaluate_hard_filters(normalized, rules_config, pet_facts=pet_facts)
    return [_reason_to_payload(reason) for reason in result.reasons]


def normalized_with_ages(normalized: dict[str, Any], as_of_date: date) -> dict[str, Any]:
    if not isinstance(normalized.get("applicant_birth_date"), str):
        return normalized
    applicant = dict(normalized)
    applicant["applicant_age"] = age_on(
        date.fromisoformat(applicant["applicant_birth_date"]), as_of_date
    )
    co_birth_date = applicant.get("co_applicant_birth_date")
    applicant["co_applicant_age"] = (
        age_on(date.fromisoformat(co_birth_date), as_of_date)
        if isinstance(co_birth_date, str)
        else None
    )
    applicant["child_details"] = [
        {
            **child,
            "age": age_on(date.fromisoformat(child["birth_date"]), as_of_date),
        }
        if isinstance(child.get("birth_date"), str)
        else dict(child)
        for child in normalized.get("child_details", [])
    ]
    return applicant
