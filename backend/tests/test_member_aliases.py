"""Shared consolidation preserves each member's own intent, including late views."""

import pytest
from sqlalchemy import event, select

from app.db.models import Analysis, MemberRanking, User, UserRole
from app.services.ranking.analysis import apply_consolidation, create_analysis
from app.services.ranking.member_state import (
    dimension_weights,
    get_or_reconcile_member_ranking,
    tier_history,
)
from tests.application_support import current_opening_id
from tests.ranking_support import a_pattern_report, setup_app


@pytest.mark.parametrize("materialized", [False, True])
@pytest.mark.parametrize("drop_tier", [0, 1, None])
@pytest.mark.parametrize("keep_placed", [False, True])
def test_consolidation_preserves_personal_priority(materialized, drop_tier, keep_placed) -> None:
    _, db, _ = setup_app(role=UserRole.MEMBER)
    initiator = db.scalar(select(User))
    other = User(email="other@example.test", display_name="Other", role=UserRole.MEMBER)
    db.add(other)
    db.commit()
    opening_id = current_opening_id(db)
    report = a_pattern_report()
    keep, drop = [dimension.key for dimension in report.dimensions]
    prior = create_analysis(db, user=initiator, opening_id=opening_id,
                            report=report, inputs_fingerprint="f", narrative=None)
    other_prior = get_or_reconcile_member_ranking(db, prior, other)
    tiers = [{"id": "top", "label": "Top", "dimension_keys": []},
             {"id": "lower", "label": "Lower", "dimension_keys": [keep] if keep_placed else []}]
    if drop_tier is not None:
        tiers[drop_tier]["dimension_keys"].append(drop)
    other_prior.run_state = {"tiers": tiers, "proposed_dimensions": ["Personal proposal"]}
    db.commit()
    current = create_analysis(db, user=initiator, opening_id=opening_id,
                              report=report, inputs_fingerprint="f", narrative=None)
    if materialized:
        view = get_or_reconcile_member_ranking(db, current, other)
        view.run_state = {**view.run_state, "proposed_dimensions": ["Independent edit"]}
        db.commit()
    initiator_view = get_or_reconcile_member_ranking(db, current, initiator)
    apply_consolidation(db, current, initiator_view, merges={drop: keep},
                        audit=[], narrative=None)
    view = get_or_reconcile_member_ranking(db, current, other)
    expected_weight = 2.0 if drop_tier == 0 else 1.0 if drop_tier == 1 or keep_placed else 0.0
    assert dimension_weights(view) == {keep: expected_weight}
    assert dimension_weights(initiator_view) == {keep: 0.0}
    assert view.run_state["proposed_dimensions"] == (["Independent edit"] if materialized else [])
    state = dict(view.run_state)
    assert get_or_reconcile_member_ranking(db, current, other).run_state == state
    _, history = tier_history(db, other, opening_id)
    assert history[keep] == ("top" if drop_tier == 0 else "lower" if expected_weight else "ignore")
    assert drop not in history


def test_tier_history_loads_reports_without_per_analysis_queries() -> None:
    _, db, _ = setup_app(role=UserRole.MEMBER)
    user = db.scalar(select(User))
    opening_id = current_opening_id(db)
    for _ in range(20):
        analysis = Analysis(opening_id=opening_id, dimension_report=a_pattern_report().model_dump())
        db.add(analysis)
        db.flush()
        db.add(MemberRanking(analysis_id=analysis.id, user_id=user.id, run_state={}))
    db.commit()
    db.expire_all()
    user_id = user.id
    queries = []
    def count(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)
    event.listen(db.bind, "before_cursor_execute", count)
    try:
        tier_history(db, db.get(User, user_id), opening_id)
    finally:
        event.remove(db.bind, "before_cursor_execute", count)
    assert len(queries) == 2  # joined histories + shared aliases


def test_ignored_merged_key_reconciles_flags_without_adding_weight() -> None:
    from app.db.models import DimensionAlias

    _, db, _ = setup_app(role=UserRole.MEMBER)
    user = db.scalar(select(User))
    report = a_pattern_report()
    keep, drop = [dimension.key for dimension in report.dimensions]
    analysis = create_analysis(db, user=user, opening_id=current_opening_id(db),
                               report=report, inputs_fingerprint="f", narrative=None)
    view = get_or_reconcile_member_ranking(db, analysis, user)
    view.run_state = {"tiers": [], "new_dimension_keys": [drop],
                      "acknowledged_requested_keys": [drop], "proposed_dimensions": ["Keep my proposal"]}
    db.add(DimensionAlias(alias_key=drop, canonical_key=keep))
    db.commit()
    view = get_or_reconcile_member_ranking(db, analysis, user)
    assert view.run_state["new_dimension_keys"] == []
    assert view.run_state["acknowledged_requested_keys"] == [keep]
    assert view.run_state["proposed_dimensions"] == ["Keep my proposal"]
    assert not any(dimension_weights(view).values())
