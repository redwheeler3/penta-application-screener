"""Keep opening announcements, applicant cards and initial screening rules in agreement."""

from datetime import UTC, datetime

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.time import pacific_today
from app.db.models import Application, ApplicationParticipation, OpeningRules
from app.schemas.applicant.answers import CanonicalApplicationAnswers
from app.services.applications.intake import normalize_answers
from app.services.eligibility.evaluation import union_eligible_application_ids
from app.services.openings.subscriptions import save_subscription
from tests.applicant.support import sample_answers
from tests.test_vacancy_notifications import _app_and_db, _opening_payload


@pytest.mark.anyio
@pytest.mark.parametrize(("beds", "limits", "bounds", "sentence", "counts", "eligible"), [
    (1, {}, (None, 0), "One or two adults and no children", [0, 1], [True, False]),
    (1, {"minChildren": 0}, (0, 0), "One or two adults and no children", [0, 1], [True, False]),
    (2, {}, (1, None), "One or two adults plus at least one child under 18", [0, 1, 5], [False, True, True]),
    (3, {}, (2, None), "One or two adults plus at least two children under 18", [1, 2, 5], [False, True, True]),
    (2, {"minChildren": None, "maxChildren": 2}, (None, 2), "One or two adults plus up to 2 children under 18", [0, 2, 3], [True, True, False]),
    (3, {"minChildren": None, "maxChildren": None}, (None, None), "One or two adults, with or without children", [0, 5], [True, True]),
    (2, {"minChildren": 2, "maxChildren": 3}, (2, 3), "One or two adults plus 2 to 3 children under 18", [1, 2, 4], [False, True, False]),
])
async def test_confirmed_household_across_consumers(beds, limits, bounds, sentence, counts, eligible):
    app, db, sender = _app_and_db()
    save_subscription(db, email="fiction@example.com", unit_sizes={beds}, source="test")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/openings", json={**_opening_payload(), "unitSizeBedrooms": beds, **limits})
        assert created.status_code == 200
        opening = created.json()["openings"][0]
        oid = opening["id"]
        assert (opening["minChildren"], opening["maxChildren"]) == bounds
        assert opening["householdSummary"] == sentence
        facts = {k: opening[k] for k in ("unitSizeBedrooms", "minChildren", "maxChildren", "housingChargeCents", "applicationOpenDate", "applicationCloseDate", "moveInDate")}
        preview = (await client.post("/openings/preview", json=facts)).json()
        published = await client.post(f"/openings/{oid}/open", json={"original": facts, "expectedVariants": preview["variants"]})
        assert published.status_code == 200
        assert sentence in sender.messages[0].text_body
        assert sentence in sender.messages[0].html_body
        card = (await client.get("/applicant/openings")).json()["openings"][0]
        assert card["householdSummary"] == sentence
        rules = db.scalar(select(OpeningRules).where(OpeningRules.opening_id == oid)).rules
        assert (rules["min_children"], rules["max_children"]) == bounds
        ids = []
        for index, count in enumerate(counts):
            email = f"family-{index}@example.com"
            payload = sample_answers(email=email)
            payload["children"] = [{"firstName": "Child", "lastName": "Example", "birthDate": "2020-01-01"} for _ in range(count)]
            answers = CanonicalApplicationAnswers.model_validate(payload)
            application = Application(primary_email=email, raw_row={}, raw_row_hash=email, normalized=normalize_answers(answers, as_of_date=pacific_today()), submitted_at=datetime.now(UTC))
            db.add(application)
            db.flush()
            db.add(ApplicationParticipation(application_id=application.id, opening_id=oid, applied_at=datetime.now(UTC)))
            ids.append(application.id)
        db.commit()
        pool = union_eligible_application_ids(db, oid)
        assert [aid in pool for aid in ids] == eligible
        published_facts = {**facts, "applicationOpenDate": pacific_today().isoformat()}
        refused = await client.put(f"/openings/{oid}", json={"original": published_facts, "changes": {**published_facts, "minChildren": 0, "maxChildren": 6}})
        assert refused.status_code == 422


@pytest.mark.anyio
async def test_preparing_edit_and_invalid_child_limits():
    app, db, _ = _app_and_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for bad in ({"minChildren": 3, "maxChildren": 2}, {"minChildren": -1}, {"maxChildren": 1.5}):
            assert (await client.post("/openings", json={**_opening_payload(), **bad})).status_code == 422
        opening = (await client.post("/openings", json=_opening_payload())).json()["openings"][0]
        facts = {k: opening[k] for k in ("unitSizeBedrooms", "minChildren", "maxChildren", "housingChargeCents", "applicationOpenDate", "applicationCloseDate", "moveInDate")}
        edited = {**facts, "minChildren": None, "maxChildren": 2}
        ack = await client.put(f"/openings/{opening['id']}", json={"original": facts, "changes": edited})
        assert ack.status_code == 200
        assert ack.json()["saved"]["householdSummary"] == "One or two adults plus up to 2 children under 18"
        assert db.scalar(select(OpeningRules)).rules["max_children"] == 2
        stale = await client.put(f"/openings/{opening['id']}", json={"original": facts, "changes": facts})
        assert stale.status_code == 409


def test_eighteenth_birthday_and_personal_child_rules_leave_public_facts_intact():
    from datetime import date, timedelta

    from app.db.models import Opening, User
    from app.schemas.settings import EligibilityRules
    from app.services.eligibility.rules import (
        hard_filter_reasons_for,
        rules_config_for,
        save_member_rules,
    )
    from app.services.openings.vacancy_notifications import opening_email_details

    _, db, _ = _app_and_db()
    o = Opening(unit_size_bedrooms=2, housing_charge_cents=90000, application_open_date=date(2026,1,1),
        application_close_date=date(2026,12,25), move_in_date=date(2027,1,1), published_at=datetime.now(UTC))
    db.add(o)
    db.flush()
    from app.services.eligibility.rules import create_opening_rules
    record = create_opening_rules(db, o)
    db.commit()
    user = db.scalar(select(User))
    day = date(2026, 11, 25)
    answers = sample_answers()
    answers["children"] = [{"firstName": "Child", "lastName": "Example", "birthDate": "2008-11-25"}]
    data = CanonicalApplicationAnswers.model_validate(answers)
    for on, expected in ((day - timedelta(days=1), False), (day, True)):
        submitted = datetime(on.year, on.month, on.day, 18, tzinfo=UTC)
        a = Application(normalized=normalize_answers(data, as_of_date=on), submitted_at=submitted)
        reasons = hard_filter_reasons_for(rules_config_for(db,user.id,o.id), a)
        assert any(r["code"] == "child_age_over_max" for r in reasons) == expected
    mine = EligibilityRules.model_validate(record.rules).model_copy(update={"min_children": 3})
    save_member_rules(db, user.id, o.id, mine)
    assert rules_config_for(db, user.id, o.id).min_children == 3
    assert record.rules["min_children"] == 1
    assert opening_email_details(o)["household_summary"] == "One or two adults plus at least one child under 18"


@pytest.mark.anyio
async def test_one_bedroom_replay_preserves_a_zero_minimum_receipt():
    app, _, _ = _app_and_db()
    payload = {**_opening_payload(), "unitSizeBedrooms": 1}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        saved = await client.post("/openings", json={**payload, "minChildren": 0})
        assert saved.status_code == 200
        replay = await client.post("/openings", json=payload)
        assert replay.status_code == 200
        assert replay.json()["openings"] == saved.json()["openings"]
        changed = await client.post("/openings", json={**payload, "minChildren": None})
        assert changed.status_code == 409
