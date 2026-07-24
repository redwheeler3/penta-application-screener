"""Unit tests for the "revived" dimension label (``revived_flag_keys``).

The badge is presence-derived and reconcile-independent (the reconcile pass was
removed in the fan-out redesign; discovery re-surfacing a dropped axis is now the
route to revival). These pin that "revived" means seen-in-an-earlier-run AND
absent-from-the-immediately-prior-run — a genuine gap, not merely "seen before".
"""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.schemas import PoolDimension, PoolDimensionReport
from app.db.models import Analysis, Base, MemberRanking, User, UserRole
from app.services.analysis import revived_flag_keys


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


def _run_with(db: Session, *, dim_keys: list[str], flagged: list[str] | None = None) -> MemberRanking:
    """A minimal shared Analysis carrying just a dimension report, plus this member's
    MemberRanking with its flagged set — enough for the read-time label derivation, no
    full rank chain. Returns the member's ranking (what revived_flag_keys reads)."""
    user = db.scalar(select(User))
    analysis = Analysis(
        dimension_report=PoolDimensionReport(
            dimensions=[
                PoolDimension(key=k, name=k, definition="d", high_end="high", low_end="low", why_it_differentiates="w")
                for k in dim_keys
            ],
        ).model_dump(mode="json"),
    )
    db.add(analysis)
    db.flush()
    ranking = MemberRanking(
        analysis_id=analysis.id,
        user_id=user.id,
        run_state={"new_dimension_keys": flagged or []},
    )
    db.add(ranking)
    db.commit()
    return ranking


def test_revived_label_needs_a_gap() -> None:
    # Three runs: 'x' is present, gone, then back-and-flagged. 'y' was never seen before
    # the run that flags it (genuinely new). revived_flag_keys should label only 'x'.
    db = make_db()
    _run_with(db, dim_keys=["x"])                       # run 1: x present
    _run_with(db, dim_keys=[])                          # run 2: x gone (the gap)
    run3 = _run_with(db, dim_keys=["x", "y"], flagged=["x", "y"])  # run 3: x back, y new

    # 'x' was seen in run 1 (before the gap) → revived; 'y' never seen before → new.
    assert revived_flag_keys(db, run3) == ["x"]


def test_recovered_not_revived_when_present_last_run() -> None:
    # A key NEVER seen before its flagging run is not labelled revived. (The gap
    # guarantee comes from carry_forward_layout only flagging absent-from-prior keys;
    # here we pin the history side: no earlier appearance → new, not revived.)
    db = make_db()
    run1 = _run_with(db, dim_keys=["x"], flagged=["x"])  # first run, x flagged, no prior
    assert revived_flag_keys(db, run1) == []  # nothing earlier → not revived (it's new)
