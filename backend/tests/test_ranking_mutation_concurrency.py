from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.api.ranking.shortlist import _require_viewed_analysis
from app.core.problems import Problem
from app.db.models import (
    Analysis,
    Base,
    MemberRanking,
    MemberRules,
    Opening,
    User,
    UserRole,
)
from app.schemas.settings import EligibilityRules
from app.services.eligibility.rules import save_member_rules
from app.services.ranking.member_state import (
    change_proposal,
    get_or_reconcile_member_ranking,
    set_tiers,
)
from app.services.run_lock import acquire_run_lock, ensure_lock_row
from tests.db_support import memory_engine
from tests.ranking_support import a_pattern_report


def seed(engine):
    factory = sessionmaker(bind=engine, autoflush=False)
    today = datetime.now(UTC).date()
    with factory() as db:
        user = User(email="synthetic@example.com", display_name="Synthetic Member", role=UserRole.MEMBER)
        opening = Opening(unit_size_bedrooms=2, housing_charge_cents=125000,
            application_open_date=today, application_close_date=today + timedelta(days=10),
            move_in_date=today + timedelta(days=30), published_at=datetime.now(UTC))
        db.add_all([user, opening])
        db.flush()
        analysis = Analysis(opening_id=opening.id, dimension_report=a_pattern_report().model_dump(mode="json"))
        db.add(analysis)
        db.flush()
        ids = user.id, opening.id, analysis.id
        db.commit()
        ensure_lock_row(db)
    return factory, ids


@pytest.mark.parametrize("proposals_first", [True, False])
def test_stale_member_snapshots_preserve_independent_writes(proposals_first):
    factory, (user_id, _opening_id, analysis_id) = seed(memory_engine())
    with factory() as db:
        member_id = get_or_reconcile_member_ranking(db, db.get(Analysis, analysis_id), db.get(User, user_id)).id
    with factory() as proposals, factory() as tiers:
        p = proposals.get(MemberRanking, member_id)
        t = tiers.get(MemberRanking, member_id)
        layout = [{"id": "important", "label": "Important", "dimension_keys": ["skills_offered"]}]
        if proposals_first:
            change_proposal(proposals, p, operation="add", text="Saved suggestion")
            set_tiers(tiers, t, layout)
        else:
            set_tiers(tiers, t, layout)
            change_proposal(proposals, p, operation="add", text="Saved suggestion")
    with factory() as db:
        state = db.get(MemberRanking, member_id).run_state
        assert state["proposed_dimensions"] == ["Saved suggestion"]
        assert state["tiers"] == layout


@pytest.mark.parametrize("existing_view", [True, False])
def test_rank_cannot_start_between_policy_check_and_member_save(tmp_path, existing_view):
    engine = create_engine(f"sqlite:///{(tmp_path / 'ranking.db').as_posix()}", connect_args={"timeout": 0.02})
    Base.metadata.create_all(engine)
    factory, (user_id, opening_id, analysis_id) = seed(engine)
    try:
        if existing_view:
            with factory() as db:
                get_or_reconcile_member_ranking(db, db.get(Analysis, analysis_id), db.get(User, user_id))
        with factory() as editor:
            view = _require_viewed_analysis(editor, opening_id, analysis_id, editor.get(User, user_id))
            with factory() as rank:
                with pytest.raises(OperationalError, match="locked"):
                    acquire_run_lock(rank, user_id=user_id, kind="rank")
            change_proposal(editor, view, operation="add", text="Included before Rank")
        with factory() as rank:
            assert acquire_run_lock(rank, user_id=user_id, kind="rank") is not None
            assert rank.scalar(select(MemberRanking)).run_state["proposed_dimensions"] == ["Included before Rank"]
    finally:
        engine.dispose()


def test_edit_rechecks_a_lease_cached_before_rank_started():
    factory, (user_id, opening_id, analysis_id) = seed(memory_engine())
    from app.services.run_lock import rank_run_in_progress

    with factory() as editor:
        assert not rank_run_in_progress(editor)
        with factory() as rank:
            acquire_run_lock(rank, user_id=user_id, kind="rank")
        with pytest.raises(Problem, match="ranking is in progress"):
            _require_viewed_analysis(editor, opening_id, analysis_id, editor.get(User, user_id))


def test_competing_first_rule_saves_share_one_row(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'rules.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory, (user_id, opening_id, _analysis_id) = seed(engine)
    writes = Barrier(2)

    @event.listens_for(engine, "before_cursor_execute")
    def overlap_inserts(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO member_rules"):
            writes.wait(timeout=3)

    def save(income):
        with factory() as db:
            return save_member_rules(db, user_id, opening_id, EligibilityRules(income_min=income)).income_min

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, [75000, 80000]))
        assert results == [75000, 80000]
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(MemberRules)) == 1
            assert db.scalar(select(MemberRules)).rules["income_min"] in results
    finally:
        engine.dispose()


@pytest.mark.parametrize("second_operation", ["add", "remove"])
def test_stale_tabs_preserve_individual_proposal_intent(second_operation):
    factory, (user_id, opening_id, analysis_id) = seed(memory_engine())
    with factory() as db:
        view = get_or_reconcile_member_ranking(db, db.get(Analysis, analysis_id), db.get(User, user_id))
        change_proposal(db, view, operation="add", text="Existing")
        member_id = view.id
    with factory() as first, factory() as second:
        a = first.get(MemberRanking, member_id)
        b = second.get(MemberRanking, member_id)
        assert a.run_state == b.run_state
        change_proposal(first, a, operation="add", text="First")
        change_proposal(second, b, operation=second_operation, text="Second" if second_operation == "add" else "Existing")
    with factory() as check:
        proposals = check.get(MemberRanking, member_id).run_state["proposed_dimensions"]
        assert proposals == (["Existing", "First", "Second"] if second_operation == "add" else ["First"])
        view = _require_viewed_analysis(check, opening_id, analysis_id, check.get(User, user_id))
        change_proposal(check, view, operation="add", text=" First ")
        assert check.get(MemberRanking, member_id).run_state["proposed_dimensions"] == proposals
