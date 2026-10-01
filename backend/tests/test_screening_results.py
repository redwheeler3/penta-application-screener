"""Latest screening evidence stays consistent across flags, pet facts, and traces."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import event

from app.db.models import Application, ApplicationAIResult
from app.services.applications.screening_results import (
    latest_screening_results,
    screening_findings_by_app,
)
from tests.db_support import memory_session


def test_latest_results_are_scoped_and_use_id_to_break_timestamp_ties() -> None:
    with memory_session() as db:
        applications = [
            Application(primary_email=f"review-{index}@example.com", raw_row={}, raw_row_hash=str(index))
            for index in range(3)
        ]
        db.add_all(applications)
        db.flush()
        now = datetime.now(UTC)
        old = ApplicationAIResult(
            application_id=applications[0].id, kind="screening", cache_key="old",
            model_id="mock", prompt_version="test", created_at=now - timedelta(seconds=1), output={},
        )
        first = ApplicationAIResult(
            application_id=applications[0].id, kind="screening", cache_key="first",
            model_id="mock", prompt_version="test", created_at=now, output={},
        )
        latest = ApplicationAIResult(
            application_id=applications[0].id, kind="screening", cache_key="latest",
            model_id="mock", prompt_version="test", created_at=now, output={},
        )
        unrelated = ApplicationAIResult(
            application_id=applications[1].id, kind="screening", cache_key="unrelated",
            model_id="mock", prompt_version="test", created_at=now, output={},
        )
        other_pass = ApplicationAIResult(
            application_id=applications[0].id, kind="dimension_scoring:x", cache_key="other",
            model_id="mock", prompt_version="test", created_at=now + timedelta(seconds=1), output={},
        )
        db.add_all([old, first, latest, unrelated, other_pass])
        db.flush()
        results = latest_screening_results(db, [applications[0].id, applications[2].id])
        assert list(results) == [applications[0].id]
        assert results[applications[0].id].id == latest.id


def test_flags_and_pets_share_one_query_and_never_reuse_older_pet_facts() -> None:
    with memory_session() as db:
        application = Application(primary_email="review@example.com", raw_row={}, raw_row_hash="review")
        db.add(application)
        db.flush()
        now = datetime.now(UTC)
        db.add_all([
            ApplicationAIResult(
                application_id=application.id, kind="screening", cache_key="pets",
                model_id="mock", prompt_version="test", created_at=now - timedelta(seconds=1),
                output={"flags": [], "pets": {"dogs": 2, "cats": 0, "other_pets": []}},
            ),
            ApplicationAIResult(
                application_id=application.id, kind="screening", cache_key="flags",
                model_id="mock", prompt_version="test", created_at=now,
                output={"flags": [{"category": "fake_contact"}]},
            ),
        ])
        db.flush()
        statements = []

        def capture_query(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture_query)
        flags, pets = screening_findings_by_app(db, [application.id])
        assert flags[application.id] == [{"category": "fake_contact"}]
        assert application.id not in pets
        assert len(statements) == 1
        assert latest_screening_results(db, []) == {}
        assert len(statements) == 1


def test_clean_screening_preserves_zero_pet_counts_and_empty_flags() -> None:
    with memory_session() as db:
        application = Application(primary_email="review@example.com", raw_row={}, raw_row_hash="review")
        db.add(application)
        db.flush()
        db.add(ApplicationAIResult(
            application_id=application.id, kind="screening", cache_key="clean",
            model_id="mock", prompt_version="test",
            output={"flags": [], "pets": {"dogs": 0, "cats": 0, "other_pets": []}},
        ))
        db.flush()
        flags, pets = screening_findings_by_app(db, [application.id])
        assert flags[application.id] == []
        assert pets[application.id].dogs == 0
        assert pets[application.id].cats == 0
