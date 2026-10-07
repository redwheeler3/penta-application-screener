from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.models import (
    MagicLinkPurpose,
    MagicLinkToken,
    Opening,
    PasswordlessIdentityKind,
)
from app.schemas.applicant.answers import WorkingApplicationAnswers
from app.services.applications.intake import create_application
from app.services.auth.passwordless import issue_magic_link
from tests.applicant.support import app_and_db, link_from_email, sample_answers


def linked_application(db):
    application = create_application(db, 'old@example.com',
        WorkingApplicationAnswers.model_validate(sample_answers('old@example.com')),
        saved_at=datetime.now(UTC), opening_ids=[db.scalar(select(Opening.id))])
    issued = issue_magic_link(db, identity_kind=PasswordlessIdentityKind.APPLICANT,
        email=application.primary_email, purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        application_id=application.id)
    db.commit()
    return application, issued


@pytest.mark.anyio
async def test_superseded_access_proof_cannot_regain_current_profile():
    app, db, sender = app_and_db()
    _application, old = linked_application(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://testserver') as owner:
        await owner.post('/applicant/access-links/open', json={'token': old.token})
        assert (await owner.post('/applicant/application/email-change', json={'newEmail': 'new@example.com'})).status_code == 202
        changed = await owner.post('/applicant/access-links/open', json={'token': link_from_email(sender)})
        assert changed.json()['currentEmail'] == 'new@example.com'
    count = len(sender.messages)
    async with AsyncClient(transport=transport, base_url='http://testserver') as outsider:
        regenerated = await outsider.post('/applicant/access-links/regenerate', json={'token': old.token})
        assert regenerated.json()['targetAvailable'] is False
        assert (await outsider.get('/applicant/application')).status_code == 401
    assert len(sender.messages) == count


@pytest.mark.anyio
@pytest.mark.parametrize('resolution', ['cancel', 'complete'])
async def test_resolved_email_change_cannot_be_restarted(resolution):
    app, db, sender = app_and_db()
    _application, old = linked_application(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://testserver') as owner:
        await owner.post('/applicant/access-links/open', json={'token': old.token})
        await owner.post('/applicant/application/email-change', json={'newEmail': 'new@example.com'})
        change = link_from_email(sender)
        if resolution == 'cancel':
            assert (await owner.delete('/applicant/application/email-change')).status_code == 204
        else:
            assert (await owner.post('/applicant/access-links/open', json={'token': change})).json()['state'] == 'valid'
    count = len(sender.messages)
    async with AsyncClient(transport=transport, base_url='http://testserver') as outsider:
        result = await outsider.post('/applicant/access-links/regenerate', json={'token': change})
        assert result.json()['targetAvailable'] is False
    assert len(sender.messages) == count


@pytest.mark.anyio
async def test_access_link_must_still_match_identity_at_redemption():
    app, db, _sender = app_and_db()
    application, old = linked_application(db)
    # A credential issued before an intervening identity change cannot prove the new address.
    application.primary_email = 'new@example.com'
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        opened = await client.post('/applicant/access-links/open', json={'token': old.token})
        assert opened.json()['state'] == 'abandoned'
        assert (await client.get('/applicant/application')).status_code == 401


@pytest.mark.anyio
async def test_unused_expired_email_change_can_be_renewed():
    app, db, sender = app_and_db()
    _application, old = linked_application(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        await client.post('/applicant/access-links/open', json={'token': old.token})
        await client.post('/applicant/application/email-change', json={'newEmail': 'new@example.com'})
        change = link_from_email(sender)
        record = db.scalar(select(MagicLinkToken).where(MagicLinkToken.purpose == MagicLinkPurpose.EMAIL_CHANGE))
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        record.created_at = datetime.now(UTC) - timedelta(minutes=2)
        db.commit()
        renewed = await client.post('/applicant/access-links/regenerate', json={'token': change})
        assert renewed.json()['emailSent'] is True
        opened = await client.post('/applicant/access-links/open', json={'token': link_from_email(sender)})
        assert opened.json()['currentEmail'] == 'new@example.com'
