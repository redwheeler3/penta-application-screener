"""Administrative mutations reject an actor demoted/deactivated after admission."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.api.feedback import resolve_feedback
from app.api.settings import update_committee_default_rules, update_settings
from app.api.vacancy_subscriptions import delete_for_support
from app.core.problems import Problem
from app.core.time import pacific_today
from app.db.models import (
    ApplicationParticipation,
    EmailDelivery,
    Opening,
    User,
    UserRole,
)
from app.schemas.openings import DirectSelectionOpeningCreate
from app.schemas.settings import AppSettings, EligibilityRules
from app.schemas.vacancy_subscriptions import VacancySubscriptionLookup
from app.services.openings.direct_selection import create_direct_selection_opening
from app.services.openings.selection import (
    confirm_no_household_selected,
    confirm_opening_selection,
)
from tests.test_write_concurrency import request_sessions


@pytest.mark.parametrize("operation", ["settings", "rules", "selection", "no_household", "direct", "feedback", "subscription"])
@pytest.mark.parametrize("change", ["demote", "deactivate"])
def test_authority_is_rechecked_before_mutation(operation, change):
    factory, opening_id, admin_id, application_ids = request_sessions(closed=True)
    with factory() as admitted, factory() as revoked:
        actor = admitted.get(User, admin_id)
        opening = admitted.get(Opening, opening_id)
        changed = revoked.get(User, admin_id)
        if change == "demote":
            changed.role = UserRole.MEMBER
        else:
            changed.is_active = False
        revoked.commit()
        assert actor.role == UserRole.ADMIN
        assert actor.is_active
        def mutate():
            if operation == "settings":
                update_settings(AppSettings(), admin=actor, db=admitted)
            elif operation == "rules":
                update_committee_default_rules(EligibilityRules(), opening_id=opening_id, _admin=actor, db=admitted)
            elif operation == "selection":
                confirm_opening_selection(admitted, opening, application_ids[0], decided_by=actor)
            elif operation == "no_household":
                confirm_no_household_selected(admitted, opening, decided_by=actor)
            elif operation == "direct":
                create_direct_selection_opening(admitted, DirectSelectionOpeningCreate(applicationId=application_ids[0],
                    unitSizeBedrooms=2, housingChargeCents=100_000, moveInDate=pacific_today() + timedelta(days=30)), decided_by=actor)
            elif operation == "feedback":
                resolve_feedback(123, _admin=actor, db=admitted)
            else:
                delete_for_support(VacancySubscriptionLookup(email="synthetic@example.com"), _admin=actor, db=admitted)
        with pytest.raises(Problem) as error:
            mutate()
        assert error.value.code == "forbidden"
        admitted.rollback()
    with factory() as check:
        assert check.get(Opening, opening_id).decided_at is None
        assert all(row.outcome is None for row in check.scalars(select(ApplicationParticipation)))
        assert check.scalar(select(func.count()).select_from(EmailDelivery)) == 0
        assert check.scalar(select(func.count()).select_from(Opening)) == 1
