"""The per-member eligibility-rules resolver (M15 1d).

The deterministic hard-filter thresholds became per-member: each committee member screens
against their own numeric rules, defaulting to a shared committee baseline until they
diverge. Two stores back that model:

  - the committee default — a single ``AdminSetting`` row (key ``committee_default_rules``)
    holding an ``EligibilityRules`` blob, the shared baseline every member reads until they
    customize;
  - per-member divergence — a sparse ``MemberRules`` row, written copy-on-write only once a
    member edits their rules away from the default (most members never diverge, so most have
    no row).

This module resolves a member's *effective* rules from those two stores, builds the domain
``RulesConfig`` a member's hard-filter evaluation runs under, and serializes the on-read
reasons that replace the (now removed) stored ``hard_filter_reasons`` column.
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AdminSetting, Application, MemberRules
from app.domain.hard_filters import RulesConfig, evaluate_hard_filters
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


def rules_config_from(rules: EligibilityRules) -> RulesConfig:
    """Map an ``EligibilityRules`` blob onto the domain ``RulesConfig`` (income_min ->
    min_income, disabled_rules -> tuple). ``today`` keeps its RulesConfig default."""
    return RulesConfig(
        min_income=rules.income_min,
        max_income=rules.income_max,
        min_adult_age=rules.min_adult_age,
        max_child_age=rules.max_child_age,
        min_children=rules.min_children,
        max_children=rules.max_children,
        disabled_rules=tuple(rules.disabled_rules),
    )


def rules_config_for(db: Session, user_id: int) -> RulesConfig:
    """The domain ``RulesConfig`` for this member's effective rules — what their
    hard-filter evaluation runs under."""
    return rules_config_from(member_rules(db, user_id)[0])


def committee_default_rules_config(db: Session) -> RulesConfig:
    """The domain ``RulesConfig`` for the shared committee-default ruleset. This is the
    SHARED baseline the screening pass and the sync summary evaluate against — not any one
    member's rules."""
    return rules_config_from(committee_default_rules(db))


def _reason_to_payload(reason: Any) -> dict[str, Any]:
    """Serialize a ``FilterReason`` to the dict shape the removed stored column carried
    (code/message/details), so callers that read reasons see the same shape they always did."""
    return {"code": reason.code, "message": reason.message, "details": reason.details}


def hard_filter_reasons_for(
    rules_config: RulesConfig, application: Application
) -> list[dict[str, Any]]:
    """This member's deterministic hard-filter reasons for one applicant, computed on read
    from ``application.normalized`` + a resolved ``RulesConfig``. Same dict shape the removed
    ``hard_filter_reasons`` column stored, so it is a drop-in for the old read.

    Takes an already-resolved ``RulesConfig`` (not a user_id) so callers ranking many apps
    resolve the member's rules once and reuse it across the pool — no per-app DB read.
    """
    result = evaluate_hard_filters(application.normalized or {}, rules_config)
    return [_reason_to_payload(reason) for reason in result.reasons]
