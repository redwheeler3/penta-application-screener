"""Result references stay batched and respect applicant-data ownership."""

from sqlalchemy import delete, event, select

from app.ai.result_selection import select_results
from app.db.models import Application, ApplicationAIResult, ApplicationAISelection
from tests.db_support import add_selected_result, memory_session


def test_large_reference_batch_uses_one_statement_and_skips_unchanged_writes() -> None:
    with memory_session() as db:
        # Foreign keys are disabled here so the query-count test needs no unrelated fixtures.
        references = [(application_id, f"dimension_scoring:criterion-{dimension}", application_id * 15 + dimension)
            for application_id in range(1, 101) for dimension in range(15)]
        statements = []

        def record(_connection, cursor, statement, _parameters, _context, _many):
            statements.append((statement, cursor.rowcount))

        event.listen(db.bind, "after_cursor_execute", record)
        try:
            select_results(db, references)
            db.commit()
            assert len(statements) == 1
            assert statements[0][1] == 1500
            statements.clear()
            select_results(db, references)
            db.commit()
            assert len(statements) == 1
            assert statements[0][1] == 0
        finally:
            event.remove(db.bind, "after_cursor_execute", record)


def test_deleting_a_consumer_keeps_the_original_cached_result() -> None:
    with memory_session(foreign_keys=True) as db:
        producer = Application(primary_email="original@example.com", raw_row={}, raw_row_hash="synthetic")
        consumer = Application(primary_email="later@example.com", raw_row={}, raw_row_hash="synthetic")
        db.add_all([producer, consumer])
        db.flush()
        result = add_selected_result(db, ApplicationAIResult(application_id=producer.id, kind="screening",
            cache_key="synthetic", model_id="synthetic", prompt_version="test", output={"flags": []}))
        select_results(db, [(consumer.id, result.kind, result.id)])
        db.commit()
        db.execute(delete(Application).where(Application.id == consumer.id))
        db.commit()
        assert db.scalar(select(ApplicationAIResult)) is result
        assert db.scalar(select(ApplicationAISelection)).application_id == producer.id
        # Purging the original applicant must also purge its derived data and references.
        db.execute(delete(Application).where(Application.id == producer.id))
        db.commit()
        assert db.scalar(select(ApplicationAIResult)) is None
        assert db.scalar(select(ApplicationAISelection)) is None
