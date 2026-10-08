"""Shared consolidation preserves each member's own intent, including late views."""

import pytest
from sqlalchemy import event, select

from app.db.models import Analysis, MemberRanking, User, UserRole
from app.schemas.settings import AppSettings
from app.services.ranking.analysis import apply_consolidation, create_analysis
from app.services.ranking.member_state import (
    dimension_weights,
    get_or_reconcile_member_ranking,
    set_tiers,
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
                        audit=[], narrative=None, settings=AppSettings())
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
    assert view.run_state["new_dimension_keys"] == [drop]
    assert view.run_state["acknowledged_requested_keys"] == [drop]
    assert view.run_state["proposed_dimensions"] == ["Keep my proposal"]
    assert not any(dimension_weights(view).values())


@pytest.mark.parametrize("materialized", [False, True])
@pytest.mark.parametrize("both_keys", [False, True])
def test_other_opening_alias_preserves_target_report_keys_and_member_intent(materialized, both_keys):
    from app.db.models import DimensionAlias, Opening
    from tests.application_support import current_opening

    _, db, _ = setup_app(role=UserRole.MEMBER)
    user = db.scalar(select(User))
    opening_a = current_opening(db)
    opening_b = Opening(unit_size_bedrooms=1, housing_charge_cents=100000,
        application_open_date=opening_a.application_open_date,
        application_close_date=opening_a.application_close_date,
        move_in_date=opening_a.move_in_date)
    db.add(opening_b)
    db.flush()
    report = a_pattern_report()
    keep, drop = [dimension.key for dimension in report.dimensions]
    create_analysis(db, user=user, opening_id=opening_a.id, report=report,
        inputs_fingerprint="a", narrative=None)
    target = report if both_keys else report.model_copy(update={"dimensions": [report.dimensions[1]]})
    prior = create_analysis(db, user=user, opening_id=opening_b.id, report=target,
        inputs_fingerprint="b", narrative=None)
    view = get_or_reconcile_member_ranking(db, prior, user)
    view.run_state = {"tiers": [{"id": "top", "label": "Top", "dimension_keys": [drop]}],
        "new_dimension_keys": [drop], "acknowledged_requested_keys": [drop]}
    db.commit()
    if not materialized:
        prior = create_analysis(db, user=user, opening_id=opening_b.id, report=target,
            inputs_fingerprint="b", narrative=None)
        db.delete(db.scalar(select(MemberRanking).where(MemberRanking.analysis_id == prior.id)))
        db.commit()
    db.add_all([DimensionAlias(alias_key=drop, canonical_key="middle"),
                DimensionAlias(alias_key="middle", canonical_key=keep)])
    db.commit()
    view = get_or_reconcile_member_ranking(db, prior, user)
    assert dimension_weights(view)[drop] == 1.0
    if both_keys:
        assert dimension_weights(view)[keep] == 0.0
    if materialized:
        assert view.run_state["new_dimension_keys"] == [drop]
        assert view.run_state["acknowledged_requested_keys"] == [drop]
    assert view.run_state["tiers"][0]["dimension_keys"] == [drop]


@pytest.mark.parametrize("materialized", [False, True])
def test_report_owned_intermediate_survivor_preserves_prior_placement(materialized):
    from app.ai.schemas import PoolDimensionReport
    from app.db.models import DimensionAlias

    _, db, _ = setup_app(role=UserRole.MEMBER)
    user = db.scalar(select(User))
    initiator = User(email="initiator@example.test", display_name="Initiator", role=UserRole.MEMBER)
    db.add(initiator)
    db.commit()
    opening_id = current_opening_id(db)
    dimension = a_pattern_report().dimensions[0]
    create_analysis(db, user=user, opening_id=opening_id,
        report=PoolDimensionReport(dimensions=[dimension.model_copy(update={"key": "c"})]),
        inputs_fingerprint="prior", narrative=None,
        tier_layout=[{"id": "top", "label": "Top", "dimension_keys": ["c"]}])
    target = create_analysis(db, user=initiator, opening_id=opening_id,
        report=PoolDimensionReport(dimensions=[dimension.model_copy(update={"key": "b"})]),
        inputs_fingerprint="target", narrative=None)
    db.add(DimensionAlias(alias_key="c", canonical_key="b"))
    db.commit()
    if materialized:
        assert dimension_weights(get_or_reconcile_member_ranking(db, target, user)) == {"b": 1.0}
    # Global history advances again while this opening retains its report with B.
    db.add(DimensionAlias(alias_key="b", canonical_key="a"))
    db.commit()
    view = get_or_reconcile_member_ranking(db, target, user)
    assert dimension_weights(view) == {"b": 1.0}
    assert view.run_state["new_dimension_keys"] == []
    assert view.run_state["tiers"][0]["dimension_keys"] == ["b"]
    assert dimension_weights(get_or_reconcile_member_ranking(db, target, initiator)) == {"b": 0.0}


@pytest.mark.parametrize("prior_ignored", [False, True])
@pytest.mark.parametrize("alias_chain", [False, True])
def test_resurfaced_priority_is_identical_before_and_after_first_view(prior_ignored, alias_chain):
    from app.ai.schemas import PoolDimensionReport
    from app.db.models import DimensionAlias

    _, db, _ = setup_app(UserRole.MEMBER)
    initiator = db.scalar(select(User))
    during = User(email="during@example.test", display_name="During", role=UserRole.MEMBER)
    after = User(email="after@example.test", display_name="After", role=UserRole.MEMBER)
    db.add_all([during, after])
    db.commit()
    users = [initiator, during, after]
    opening_id = current_opening_id(db)
    dimension, unrelated = a_pattern_report().dimensions
    older = dimension.model_copy(update={"key": "older"})
    prior_report = PoolDimensionReport(dimensions=[older, unrelated])
    prior = create_analysis(db, user=initiator, opening_id=opening_id,
        report=prior_report, inputs_fingerprint="prior", narrative=None)
    layouts = {}
    for user in users:
        layouts[user.id] = [
            {"id": f"top-{user.id}", "label": f"Top {user.id}",
             "dimension_keys": [] if prior_ignored else ["older"]},
            {"id": f"lower-{user.id}", "label": f"Lower {user.id}",
             "dimension_keys": [unrelated.key]},
        ]
        set_tiers(db, get_or_reconcile_member_ranking(db, prior, user), layouts[user.id])
        db.commit()
    if alias_chain:
        db.add(DimensionAlias(alias_key="middle", canonical_key="older"))
        db.commit()
    current = create_analysis(db, user=initiator, opening_id=opening_id,
        report=PoolDimensionReport(dimensions=[dimension.model_copy(update={"key": "newer"}), unrelated]),
        inputs_fingerprint="current", narrative=None,
        tier_layout=[{**tier, "dimension_keys": [key for key in tier["dimension_keys"] if key != "older"]}
                     for tier in layouts[initiator.id]])
    for user in [initiator, during]:
        view = get_or_reconcile_member_ranking(db, current, user)
        view.run_state = {**view.run_state, "proposed_dimensions": [f"Proposal {user.id}"]}
    db.commit()
    apply_consolidation(db, current, get_or_reconcile_member_ranking(db, current, initiator),
        merges={"newer": "middle" if alias_chain else "older"}, audit=[], narrative=None,
        settings=AppSettings())
    for user in users:
        view = get_or_reconcile_member_ranking(db, current, user)
        assert dimension_weights(view) == {"older": 0.0 if prior_ignored else 2.0, unrelated.key: 1.0}
        assert view.run_state["tiers"] == layouts[user.id]
        assert view.run_state["proposed_dimensions"] == ([] if user == after else [f"Proposal {user.id}"])
        # Repeated reads cannot revive a survivor the member explicitly ignores afterward.
        ignored = [{**tier, "dimension_keys": [key for key in tier["dimension_keys"] if key != "older"]}
                   for tier in layouts[user.id]]
        set_tiers(db, view, ignored)
        db.commit()
        for _ in range(2):
            reread = get_or_reconcile_member_ranking(db, current, user)
            assert dimension_weights(reread)["older"] == 0.0
            assert reread.run_state["tiers"] == ignored


def test_first_view_reloads_analysis_consolidated_after_its_initial_read():
    from sqlalchemy.orm import sessionmaker

    from app.ai.schemas import PoolDimensionReport

    _, db, _ = setup_app(UserRole.MEMBER)
    initiator = db.scalar(select(User))
    other = User(email="late@example.test", display_name="Late", role=UserRole.MEMBER)
    db.add(other)
    db.commit()
    dimension = a_pattern_report().dimensions[0]
    prior = create_analysis(db, user=other, opening_id=current_opening_id(db),
        report=PoolDimensionReport(dimensions=[dimension.model_copy(update={"key": "older"})]),
        inputs_fingerprint="prior", narrative=None,
        tier_layout=[{"id": "top", "label": "Top", "dimension_keys": ["older"]}])
    current = create_analysis(db, user=initiator, opening_id=prior.opening_id,
        report=PoolDimensionReport(dimensions=[dimension.model_copy(update={"key": "newer"})]),
        inputs_fingerprint="current", narrative=None)
    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    with factory() as reader:
        snapshot = reader.get(Analysis, current.id)
        member = reader.get(User, other.id)
        assert snapshot.dimension_report["dimensions"][0]["key"] == "newer"
        apply_consolidation(db, current, get_or_reconcile_member_ranking(db, current, initiator),
            merges={"newer": "older"}, audit=[], narrative=None, settings=AppSettings())
        view = get_or_reconcile_member_ranking(reader, snapshot, member)
        assert dimension_weights(view) == {"older": 1.0}


@pytest.mark.parametrize("commit", [False, True])
def test_first_view_race_releases_only_its_owned_write_transaction(commit):
    from sqlalchemy.orm import sessionmaker

    _, db, _ = setup_app(UserRole.MEMBER)
    initiator = db.scalar(select(User))
    other = User(email="racing@example.test", display_name="Racing", role=UserRole.MEMBER)
    db.add(other)
    db.commit()
    analysis = create_analysis(db, user=initiator, opening_id=current_opening_id(db),
        report=a_pattern_report(), inputs_fingerprint="current", narrative=None)
    analysis_id, other_id = analysis.id, other.id
    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    with factory() as first, factory() as second:
        winner_ids = []

        @event.listens_for(first, "do_orm_execute")
        def competing_first_view(execution):
            if execution.is_update and execution.statement.table.name == "analyses" and not winner_ids:
                winner = get_or_reconcile_member_ranking(second,
                    second.get(Analysis, analysis_id), second.get(User, other_id))
                winner_ids.append(winner.id)

        result = get_or_reconcile_member_ranking(first,
            first.get(Analysis, analysis_id), first.get(User, other_id), commit=commit)
        # A coherent post-commit SELECT may open a Session read transaction, but
        # only the caller-owned path may retain SQLite's write transaction.
        assert first.connection().connection.driver_connection.in_transaction is not commit
        assert result.id == winner_ids[0]


@pytest.mark.parametrize("merge_at", [
    "before-member-read", "after-member-read", "after-first-view-commit", "after-reconcile-commit",
])
def test_member_read_returns_coherent_criteria_priorities_and_flags_during_consolidation(merge_at):
    from sqlalchemy.orm import sessionmaker

    from app.ai.schemas import PoolDimensionReport
    from app.api.ranking.presentation import ranking_payload, run_payload
    from app.api.ranking.shortlist import _current_member_view
    from app.db.models import DimensionAlias
    from app.services.ranking.member_state import display_tiers

    _, writer, _ = setup_app(UserRole.MEMBER)
    initiator = writer.scalar(select(User))
    other = User(email="reader@example.test", display_name="Reader", role=UserRole.MEMBER)
    writer.add(other)
    writer.commit()
    opening_id = current_opening_id(writer)
    dimension = a_pattern_report().dimensions[0]
    create_analysis(writer, user=other, opening_id=opening_id,
        report=PoolDimensionReport(dimensions=[dimension.model_copy(update={"key": "older"})]),
        inputs_fingerprint="prior", narrative=None,
        tier_layout=[{"id": "top", "label": "Personal priority", "dimension_keys": ["older"]}])
    current = create_analysis(writer, user=initiator, opening_id=opening_id,
        report=PoolDimensionReport(dimensions=[dimension.model_copy(update={"key": "newer"})]),
        inputs_fingerprint="current", narrative=None)
    if merge_at != "after-first-view-commit":
        view = get_or_reconcile_member_ranking(writer, current, other)
        set_tiers(writer, view, [{"id": "top", "label": "Personal priority", "dimension_keys": ["newer"]}])
        writer.commit()
        if merge_at == "after-reconcile-commit":
            writer.add(DimensionAlias(alias_key="prior_alias", canonical_key="newer"))
            view.run_state = {**view.run_state,
                "tiers": [{"id": "top", "label": "Personal priority", "dimension_keys": ["prior_alias"]}]}
            writer.commit()
    factory = sessionmaker(bind=writer.get_bind(), autoflush=False)
    with factory() as reader:
        member = reader.get(User, other.id)
        merged = False

        def consolidate():
            nonlocal merged
            merged = True
            apply_consolidation(writer, current, get_or_reconcile_member_ranking(writer, current, initiator),
                merges={"newer": "older"}, audit=[], narrative=None, settings=AppSettings())

        @event.listens_for(reader, "do_orm_execute")
        def between_reads(execution):
            if merged or not execution.is_select:
                return
            entity = MemberRanking if merge_at == "before-member-read" else DimensionAlias
            if not merge_at.endswith("-commit") and any(
                column.get("entity") is entity for column in execution.statement.column_descriptions
            ):
                consolidate()

        @event.listens_for(reader, "after_commit")
        def after_first_view(_session):
            if merge_at.endswith("-commit") and not merged:
                consolidate()

        view = _current_member_view(reader, member, opening_id, "ranking")
        assert merged
        run = run_payload(view)
        ranking = ranking_payload(reader, view, member)
        tiers = display_tiers(view)
        expected = "newer" if merge_at == "after-member-read" else "older"
        assert [dimension.key for dimension in run.dimensions] == [expected]
        assert ranking.weights == {expected: 1.0}
        assert tiers[0]["dimension_keys"] == [expected]
        assert tiers[-1]["dimension_keys"] == []
        assert ranking.new_dimension_keys == (["newer"] if expected == "newer" else [])
        assert ranking.revived_dimension_keys == []


@pytest.mark.parametrize("acknowledged", [False, True])
@pytest.mark.parametrize("prior_ignored", [False, True])
def test_resurfaced_review_flags_match_late_views_and_preserve_explicit_acknowledgements(acknowledged, prior_ignored):
    from app.ai.schemas import PoolDimensionReport
    from app.api.ranking.presentation import ranking_payload, run_payload
    from app.services.ranking.member_state import display_tiers

    _, db, _ = setup_app(UserRole.MEMBER)
    initiator = db.scalar(select(User))
    eager = User(email="eager@example.test", display_name="Eager", role=UserRole.MEMBER)
    late = User(email="late@example.test", display_name="Late", role=UserRole.MEMBER)
    db.add_all([eager, late])
    db.commit()
    opening_id = current_opening_id(db)
    dimension, unrelated = a_pattern_report().dimensions
    older = dimension.model_copy(update={"key": "older"})
    prior = create_analysis(db, user=initiator, opening_id=opening_id,
        report=PoolDimensionReport(dimensions=[older, unrelated]), inputs_fingerprint="prior", narrative=None)
    for user in [eager, late]:
        set_tiers(db, get_or_reconcile_member_ranking(db, prior, user), [
            {"id": "top", "label": "Personal priority", "dimension_keys": [] if prior_ignored else ["older"]},
        ])
        db.commit()
    gap = create_analysis(db, user=initiator, opening_id=opening_id,
        report=PoolDimensionReport(dimensions=[unrelated]), inputs_fingerprint="gap", narrative=None)
    for user in [eager, late]:
        get_or_reconcile_member_ranking(db, gap, user)
    current = create_analysis(db, user=initiator, opening_id=opening_id,
        report=PoolDimensionReport(dimensions=[dimension.model_copy(update={"key": "newer"}), unrelated]),
        inputs_fingerprint="current", narrative=None)
    eager_view = get_or_reconcile_member_ranking(db, current, eager)
    assert eager_view.run_state["new_dimension_keys"] == ["newer"]
    eager_view.run_state = {**eager_view.run_state, "proposed_dimensions": ["Personal proposal"]}
    db.commit()
    if acknowledged:
        set_tiers(db, eager_view, eager_view.run_state["tiers"], acknowledged_keys=["newer"])
        db.commit()
    apply_consolidation(db, current, get_or_reconcile_member_ranking(db, current, initiator),
        merges={"newer": "older"}, audit=[], narrative=None, settings=AppSettings())
    for user in [eager, late]:
        view = get_or_reconcile_member_ranking(db, current, user)
        payload = ranking_payload(db, view, user)
        assert {dimension.key for dimension in run_payload(view).dimensions} == {"older", unrelated.key}
        assert payload.weights == {"older": 0.0 if prior_ignored else 1.0, unrelated.key: 0.0}
        expected_flags = [] if user == eager and acknowledged else ["older"]
        assert payload.new_dimension_keys == payload.revived_dimension_keys == expected_flags
        assert display_tiers(view)[0]["label"] == "Personal priority"
        assert view.run_state["proposed_dimensions"] == (["Personal proposal"] if user == eager else [])
        set_tiers(db, view, [{"id": "top", "label": "Personal priority", "dimension_keys": []}],
            acknowledged_keys=["older"])
        db.commit()
        for _ in range(2):
            reread = get_or_reconcile_member_ranking(db, current, user)
            assert ranking_payload(db, reread, user).new_dimension_keys == []
            assert dimension_weights(reread)["older"] == 0.0
