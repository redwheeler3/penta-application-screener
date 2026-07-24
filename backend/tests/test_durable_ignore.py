"""Durable Ignore across re-ranks (``tier_history`` + ``carry_forward_layout``).

The rule: each key restores to the tier it was MOST RECENTLY in — Ignore being a
first-class tier, not the absence of one. So a key the committee dragged to Ignore
STAYS in Ignore across re-ranks (a recent Ignore beats an older working placement),
while a key that genuinely faded from the pool and returns restores to its last-seen
tier + the revived flag.

These pin the fix for the bug where an all-Ignore board silently resurrected
dimensions into their old working tiers on the next re-rank (Ignore was modelled as
absence, so an older Critical placement won).
"""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.schemas import PoolDimension, PoolDimensionReport
from app.db.models import Analysis, Base, MemberRanking, User, UserRole
from app.services.analysis import (
    IGNORE_TIER_ID,
    carry_forward_layout,
    kept_keys,
    tier_history,
)


def make_db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    db.add(User(email="m@x.com", display_name="M", role=UserRole.MEMBER, is_active=True))
    db.commit()
    return db


def _report(*keys: str) -> dict:
    return PoolDimensionReport(
        dimensions=[
            PoolDimension(key=k, name=k, definition="d", high_end="hi", low_end="lo", why_it_differentiates="w")
            for k in keys
        ],
    ).model_dump(mode="json")


def _tier(tier_id: str, label: str, keys: list[str]) -> dict:
    return {"id": tier_id, "label": label, "dimension_keys": keys}


def _run(db: Session, *, report_keys: list[str], tiers: list[dict]) -> MemberRanking:
    """A minimal analysis carrying a dimension report + this member's stored (working)
    tiers. Ignore is every report key not in a working tier — never stored, matching
    production. Returns the member's ranking (the per-member view)."""
    user = db.scalar(select(User))
    analysis = Analysis(dimension_report=_report(*report_keys))
    db.add(analysis)
    db.flush()
    ranking = MemberRanking(
        analysis_id=analysis.id, user_id=user.id, run_state={"tiers": tiers}
    )
    db.add(ranking)
    db.commit()
    return ranking


CRIT = ("tier-s", "Critical")


def test_recent_ignore_beats_older_working_placement() -> None:
    # 'a' was Critical in run 1, then the committee dragged it to Ignore in run 2
    # (present in the report, in no working tier). Its most-recent tier is Ignore.
    db = make_db()
    _run(db, report_keys=["a"], tiers=[_tier(*CRIT, ["a"])])          # run 1: a Critical
    _run(db, report_keys=["a"], tiers=[_tier(*CRIT, [])])             # run 2: a dragged to Ignore

    _scaffold, tier_by_key = tier_history(db, db.scalar(select(User)))
    assert tier_by_key["a"] == IGNORE_TIER_ID  # recent Ignore wins, not the old Critical


def test_all_ignore_board_stays_all_ignore_on_rerank() -> None:
    # The reported bug: everything in Ignore, re-rank, and nothing should climb back.
    db = make_db()
    _run(db, report_keys=["a", "b"], tiers=[_tier(*CRIT, ["a", "b"])])  # run 1: both Critical
    _run(db, report_keys=["a", "b"], tiers=[_tier(*CRIT, [])])          # run 2: all dragged to Ignore

    scaffold, tier_by_key = tier_history(db, db.scalar(select(User)))
    # A re-rank rediscovers the same keys; carry-forward must leave them all unplaced.
    layout, flagged = carry_forward_layout(
        new_report=PoolDimensionReport.model_validate(_report("a", "b")),
        scaffold_tiers=scaffold,
        most_recent_tier_by_key=tier_by_key,
        immediately_prior_keys={"a", "b"},  # both present in run 2's report
    )
    assert all(not t["dimension_keys"] for t in layout)  # nothing placed
    assert flagged == []  # continuous in view (present last run) → no tag


def test_kept_keys_empty_after_all_ignore_rerank() -> None:
    # The invariant the user flagged: an Ignored dim is never "kept", so never injected
    # into decomposition. After an all-Ignore re-rank, the new run's kept set is empty.
    db = make_db()
    _run(db, report_keys=["a", "b"], tiers=[_tier(*CRIT, ["a", "b"])])
    _run(db, report_keys=["a", "b"], tiers=[_tier(*CRIT, [])])
    scaffold, tier_by_key = tier_history(db, db.scalar(select(User)))
    layout, _flagged = carry_forward_layout(
        new_report=PoolDimensionReport.model_validate(_report("a", "b")),
        scaffold_tiers=scaffold,
        most_recent_tier_by_key=tier_by_key,
        immediately_prior_keys={"a", "b"},
    )
    new_run = _run(db, report_keys=["a", "b"], tiers=layout)
    assert kept_keys(new_run) == []


def test_faded_from_ignore_stays_ignore_on_return() -> None:
    # 'a' was Ignored in run 1 (present but unplaced), genuinely fell out of the pool in
    # run 2 (absent from the report). Its most-recent REAL appearance was Ignore, so on
    # return it restores to Ignore — not to any older working tier.
    db = make_db()
    _run(db, report_keys=["a", "keep"], tiers=[_tier(*CRIT, ["keep"])])  # run 1: a Ignored
    _run(db, report_keys=["keep"], tiers=[_tier(*CRIT, ["keep"])])       # run 2: a gone from pool
    _scaffold, tier_by_key = tier_history(db, db.scalar(select(User)))
    assert tier_by_key["a"] == IGNORE_TIER_ID  # its last real appearance was Ignore


def test_faded_from_working_tier_restores_to_that_tier() -> None:
    # Guard against over-correcting: a key last seen in a WORKING tier (then gone from
    # the pool) still restores to that working tier when it returns.
    db = make_db()
    _run(db, report_keys=["a", "keep"], tiers=[_tier(*CRIT, ["a", "keep"])])  # run 1: a Critical
    _run(db, report_keys=["keep"], tiers=[_tier(*CRIT, ["keep"])])            # run 2: a gone
    _scaffold, tier_by_key = tier_history(db, db.scalar(select(User)))
    assert tier_by_key["a"] == "tier-s"  # last real appearance was Critical → restores there
