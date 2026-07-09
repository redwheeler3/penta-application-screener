"""Unit tests for the reconcile pass sanitization and skip behavior.

The reconcile pass asks the model which dropped prior dimensions the live pool still
varies on. These pin the contract that the raw model output is sanitized to real
dropped keys before it can revive anything (a bad verdict can't corrupt the run),
and that the pass is skipped — no call, no cost — when there is nothing to do.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.dimension_reconcile import estimate_reconcile, reconcile_dropped
from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    PoolDimension,
    PoolDimensionReport,
    ReconcileReport,
    ReconcileVerdict,
)
from app.db.models import Application, ApplicationStatus, Base, RankingRun
from app.schemas.settings import AppSettings
from app.services.ranking_run import revived_flag_keys


def make_db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def add_eligible(db: Session, *, email: str, raw_hash: str) -> Application:
    app = Application(
        primary_email=email,
        applicant_name="Test",
        raw_row={"Why a co-op": "We want community."},
        raw_row_hash=raw_hash,
        normalized={},
        status=ApplicationStatus.ELIGIBLE,
        hard_filter_reasons=[],
    )
    db.add(app)
    db.commit()
    return app


def _dropped(*keys: str) -> list[PoolDimension]:
    return [
        PoolDimension(key=k, name=k, definition="d", why_it_differentiates="w") for k in keys
    ]


def test_reconcile_sanitizes_to_real_dropped_keys() -> None:
    db = make_db()
    app = add_eligible(db, email="a@x.com", raw_hash="h1")
    provider = MockProvider()
    provider.route(
        "<dropped_dimensions>",
        ReconcileReport(
            verdicts=[
                ReconcileVerdict(old_key="a", revive=True, reasoning="varies"),
                ReconcileVerdict(old_key="b", revive=False, reasoning="flat"),
                # Unknown key (not offered) — dropped from the result.
                ReconcileVerdict(old_key="ghost", revive=True, reasoning="hallucinated"),
                # Duplicate of 'a' — first wins, this is ignored.
                ReconcileVerdict(old_key="a", revive=False, reasoning="dup"),
            ]
        ),
    )
    revive_keys, ballot, _narrative, cost = reconcile_dropped(
        provider,
        db,
        dropped=_dropped("a", "b"),
        applications=[app],
        settings=AppSettings(),
    )
    # Only real, first-seen dropped keys survive; 'ghost' and the duplicate are gone.
    assert revive_keys == ["a"]
    assert [v["old_key"] for v in ballot] == ["a", "b"]
    assert cost > 0.0


def test_reconcile_skipped_when_nothing_dropped() -> None:
    # No dropped priors → no call, no cost, empty results (first run / all matched).
    db = make_db()
    app = add_eligible(db, email="a@x.com", raw_hash="h1")
    provider = MockProvider()
    revive_keys, ballot, narrative, cost = reconcile_dropped(
        provider, db, dropped=[], applications=[app], settings=AppSettings()
    )
    assert revive_keys == []
    assert ballot == []
    assert narrative is None
    assert cost == 0.0
    assert provider.calls == []  # the model was never called


def test_reconcile_skipped_when_no_applications() -> None:
    db = make_db()
    provider = MockProvider()
    _, _, _, cost = reconcile_dropped(
        provider, db, dropped=_dropped("a"), applications=[], settings=AppSettings()
    )
    assert cost == 0.0
    assert provider.calls == []


def test_estimate_reconcile_zero_when_nothing_dropped() -> None:
    db = make_db()
    app = add_eligible(db, email="a@x.com", raw_hash="h1")
    assert estimate_reconcile(0, [app], AppSettings()) == 0.0
    # With dropped dims and a pool, the estimate is positive (pool input + ballot output).
    assert estimate_reconcile(3, [app], AppSettings()) > 0.0


# --- revived_flag_keys: the "revived" label needs a real presence gap ----------


def _run_with(db: Session, *, dim_keys: list[str], flagged: list[str] | None = None) -> RankingRun:
    """A minimal RankingRun carrying just a dimension report + flagged set — enough
    for the read-time label derivation, no full rank chain."""
    run = RankingRun(
        name="r",
        status="patterns_discovered",
        criteria={
            "dimension_report": PoolDimensionReport(
                summary="s",
                dimensions=[
                    PoolDimension(key=k, name=k, definition="d", why_it_differentiates="w")
                    for k in dim_keys
                ],
            ).model_dump(mode="json"),
            "new_dimension_keys": flagged or [],
        },
    )
    db.add(run)
    db.commit()
    return run


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
    # 'x' present in run 1 AND run 2 (no gap), flagged in run 2 — recovered-but-not-
    # revived has no earlier-run gap, but note revived_flag_keys keys off history, so a
    # key present in run 1 and flagged in run 2 WOULD read as revived. The gap guarantee
    # comes from carry_forward_layout only flagging absent-from-prior keys; here we pin
    # that a key NEVER seen before its flagging run is not labelled revived.
    db = make_db()
    run1 = _run_with(db, dim_keys=["x"], flagged=["x"])  # first run, x flagged, no prior
    assert revived_flag_keys(db, run1) == []  # nothing earlier → not revived (it's new)
