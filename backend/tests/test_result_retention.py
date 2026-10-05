"""Cached output belongs to every legally retained producer/selected consumer."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.ai.result_selection import select_results
from app.core.time import pacific_today
from app.db.models import Application, ApplicationAIResult, ApplicationAISelection
from app.services.applications.purge import purge_expired_application
from tests.db_support import memory_session


@pytest.mark.parametrize("kind", ["screening", "dimension_scoring:synthetic"])
@pytest.mark.parametrize("consumer_first", [False, True])
def test_result_survives_until_last_retained_owner_is_purged(kind, consumer_first):
    now = datetime.now(UTC)
    today = pacific_today(now=now)
    db = memory_session(foreign_keys=True)
    producer = Application(primary_email="producer@example.test", raw_row={}, raw_row_hash="same", normalized={})
    consumers = [Application(primary_email=f"consumer{i}@example.test", raw_row={}, raw_row_hash="same", normalized={}) for i in range(2)]
    db.add_all([producer, *consumers])
    db.flush()
    result = ApplicationAIResult(producer_application_id=producer.id, kind=kind, cache_key="same",
        model_id="synthetic", prompt_version="v", output={"flags": []}, cost_usd=0.123)
    db.add(result)
    db.flush()
    result_id, producer_id = result.id, producer.id
    select_results(db, [(app.id, kind, result_id) for app in [producer, *consumers]])
    db.commit()
    order = [consumers[0], producer, consumers[1]] if consumer_first else [producer, consumers[0], consumers[1]]
    for index, application in enumerate(order):
        application.retention_due_on = today
        db.commit()
        assert purge_expired_application(db, application, now=now)
        db.commit()
        db.expire_all()
        surviving = db.scalar(select(ApplicationAIResult).where(ApplicationAIResult.id == result_id))
        if index < 2:
            assert surviving.producer_application_id == producer_id
            assert surviving.cost_usd == 0.123
            assert surviving.output == {"flags": []}
        else:
            assert surviving is None
            assert db.scalars(select(ApplicationAISelection)).all() == []


def test_replacing_last_selected_reference_removes_unowned_history():
    db = memory_session(foreign_keys=True)
    consumer = Application(primary_email="consumer@example.test", raw_row={}, raw_row_hash="same", normalized={})
    db.add(consumer)
    db.flush()
    previous = ApplicationAIResult(producer_application_id=123, kind="screening", cache_key="previous",
        model_id="synthetic", prompt_version="v", output={"flags": []})
    current = ApplicationAIResult(producer_application_id=consumer.id, kind="screening", cache_key="current",
        model_id="synthetic", prompt_version="v", output={"flags": []})
    db.add_all([previous, current])
    db.flush()
    previous_id = previous.id
    select_results(db, [(consumer.id, "screening", previous_id)])
    # Changed input does not withdraw entitlement to last-consumed output.
    consumer.raw_row_hash = "resubmitted"
    consumer.retention_due_on = pacific_today() + timedelta(days=1)
    db.commit()
    assert db.scalar(select(ApplicationAIResult.id).where(ApplicationAIResult.id == previous_id)) == previous_id
    select_results(db, [(consumer.id, "screening", current.id)])
    db.commit()
    assert db.scalar(select(ApplicationAIResult.id).where(ApplicationAIResult.id == previous_id)) is None
