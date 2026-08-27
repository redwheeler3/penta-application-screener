"""Committee-union of kept axes + proposals (M15 Phase 2; ADR 0011).

A re-rank must respect the WHOLE committee, not just whoever triggered it:
  - an axis survives if ANY member placed it in a working tier ("keep-if-any-member-tiered"),
    computed from each member's most-recent tiering (so a member who skipped the last run still
    protects their axes);
  - every member's pending proposals steer the one shared discovery.

These pin ``committee_kept_keys`` and ``committee_proposed_dimensions``.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.schemas import PoolDimension, PoolDimensionReport
from app.db.models import Analysis, Base, MemberRanking, User, UserRole
from app.services.ranking_analysis import (
    committee_kept_keys,
    committee_proposed_dimensions,
)


def make_db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def add_user(db: Session, email: str) -> User:
    user = User(email=email, display_name=email, role=UserRole.MEMBER, is_active=True)
    db.add(user)
    db.commit()
    return user


def report(*keys: str) -> PoolDimensionReport:
    return PoolDimensionReport(
        dimensions=[
            PoolDimension(key=k, name=k, definition="d", high_end="hi", low_end="lo", why_it_differentiates="w")
            for k in keys
        ],
    )


def add_analysis(db: Session, *keys: str) -> Analysis:
    analysis = Analysis(dimension_report=report(*keys).model_dump(mode="json"))
    db.add(analysis)
    db.flush()
    return analysis


def tier(tier_id: str, keys: list[str]) -> dict:
    return {"id": tier_id, "label": tier_id, "dimension_keys": keys}


def add_ranking(
    db: Session, analysis: Analysis, user: User, *, tiers: list[dict] | None = None,
    proposed: list[str] | None = None,
) -> MemberRanking:
    ranking = MemberRanking(
        analysis_id=analysis.id,
        user_id=user.id,
        run_state={"tiers": tiers or [], "proposed_dimensions": proposed or []},
    )
    db.add(ranking)
    db.commit()
    return ranking


# --- keep-if-any-member-tiered ------------------------------------------------


def test_axis_survives_if_any_member_tiered_it() -> None:
    """An axis kept by member B (not the triggerer A) is still in the committee kept set."""
    db = make_db()
    a = add_user(db, "a@x.com")
    b = add_user(db, "b@x.com")
    analysis = add_analysis(db, "community", "skills")
    add_ranking(db, analysis, a, tiers=[tier("tier-s", ["community"])])  # A keeps community
    add_ranking(db, analysis, b, tiers=[tier("tier-s", ["skills"])])     # B keeps skills

    kept = committee_kept_keys(db, report("community", "skills"))
    assert kept == {"community", "skills"}  # union, not just the triggerer's


def test_ignored_axis_is_not_kept() -> None:
    """A key no member placed in a working tier (present-but-unplaced = Ignore) isn't kept."""
    db = make_db()
    a = add_user(db, "a@x.com")
    analysis = add_analysis(db, "community", "skills")
    add_ranking(db, analysis, a, tiers=[tier("tier-s", ["community"])])  # skills unplaced

    assert committee_kept_keys(db, report("community", "skills")) == {"community"}


def test_kept_from_a_members_most_recent_tiering_even_if_they_skipped_last_run() -> None:
    """A member's kept axes come from their MOST-RECENT tiering across all their rankings —
    so a member who didn't open the immediately-prior analysis still protects what they tiered."""
    db = make_db()
    a = add_user(db, "a@x.com")
    b = add_user(db, "b@x.com")
    first = add_analysis(db, "community", "skills")
    add_ranking(db, first, b, tiers=[tier("tier-s", ["skills"])])  # B tiered skills on run 1
    # Run 2: only A opens it (B has no ranking on `second`).
    second = add_analysis(db, "community", "skills")
    add_ranking(db, second, a, tiers=[tier("tier-s", ["community"])])

    # B skipped run 2, but their run-1 keep of "skills" still protects it.
    kept = committee_kept_keys(db, report("community", "skills"))
    assert kept == {"community", "skills"}


def test_kept_restricted_to_current_report_keys() -> None:
    """A stale placement naming a dropped dimension can't resurrect it — only keys present
    in the passed report count."""
    db = make_db()
    a = add_user(db, "a@x.com")
    analysis = add_analysis(db, "community")
    add_ranking(db, analysis, a, tiers=[tier("tier-s", ["community", "gone"])])

    assert committee_kept_keys(db, report("community")) == {"community"}


def test_kept_empty_on_first_run() -> None:
    db = make_db()
    add_user(db, "a@x.com")
    assert committee_kept_keys(db, None) == set()


# --- shared-union discovery merge ---------------------------------------------


def test_proposals_union_across_members() -> None:
    db = make_db()
    a = add_user(db, "a@x.com")
    b = add_user(db, "b@x.com")
    analysis = add_analysis(db, "community")
    add_ranking(db, analysis, a, proposed=["garden use"])
    add_ranking(db, analysis, b, proposed=["transit access"])

    assert committee_proposed_dimensions(db, analysis) == ["garden use", "transit access"]


def test_proposals_deduped_case_insensitively_first_wins() -> None:
    db = make_db()
    a = add_user(db, "a@x.com")
    b = add_user(db, "b@x.com")
    analysis = add_analysis(db, "community")
    add_ranking(db, analysis, a, proposed=["Garden Use"])
    add_ranking(db, analysis, b, proposed=["garden use", "transit access"])

    # Case-insensitive dedupe; first-seen wording ("Garden Use") kept; stable order.
    assert committee_proposed_dimensions(db, analysis) == ["Garden Use", "transit access"]


def test_proposals_empty_on_first_run() -> None:
    db = make_db()
    add_user(db, "a@x.com")
    assert committee_proposed_dimensions(db, None) == []
