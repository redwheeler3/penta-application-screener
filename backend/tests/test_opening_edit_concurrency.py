"""An opening save owns only the facts its editor compared against."""

from datetime import timedelta

import pytest

from app.core.problems import Problem
from app.db.models import Opening
from app.schemas.openings import OpeningUpdate
from app.services.openings.catalog import update_opening
from tests.test_write_concurrency import request_sessions


def test_stale_opening_save_cannot_undo_another_admins_change() -> None:
    factory, opening_id, _, _ = request_sessions(closed=False)
    with factory() as db:
        opening = db.get(Opening, opening_id)
        original = {"unitSizeBedrooms": opening.unit_size_bedrooms, "housingChargeCents": opening.housing_charge_cents,
            "applicationOpenDate": opening.application_open_date, "applicationCloseDate": opening.application_close_date,
            "moveInDate": opening.move_in_date}
    first = OpeningUpdate(original=original, changes={**original, "housingChargeCents": 150_000})
    second = OpeningUpdate(original=original, changes={**original, "applicationCloseDate": original["applicationCloseDate"] + timedelta(days=1)})
    with factory() as db:
        update_opening(db, db.get(Opening, opening_id), first)
    with factory() as db:
        with pytest.raises(Problem) as error:
            update_opening(db, db.get(Opening, opening_id), second)
        assert error.value.code == "stale_opening"
        assert error.value.status == 409
        db.rollback()
        assert db.get(Opening, opening_id).housing_charge_cents == 150_000
        assert db.get(Opening, opening_id).application_close_date == original["applicationCloseDate"]
