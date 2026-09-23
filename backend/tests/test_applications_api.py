"""Committee application reads and human working-state mutations."""

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.dependencies import require_current_user
from app.db.models import (
    ApplicationCommitteeNote,
    ApplicationNote,
    ApplicationParticipation,
    ApplicationShortlist,
    ApplicationStar,
    ApplicationVersion,
    Opening,
    User,
    UserRole,
)
from tests.committee_app_support import (
    add_eligible_application as add_eligible,
)
from tests.committee_app_support import (
    setup_committee_app as setup_app,
)


@pytest.mark.anyio
async def test_private_notes_are_scoped_to_the_current_member() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="note@x.com", raw_hash="h1")
    first_member = db.scalar(select(User).where(User.email == "admin@x.com"))
    assert first_member is not None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        saved = await client.put(f"/applications/{application.id}/note", json={"note": "Call references."})
        assert saved.status_code == 200
        assert saved.json()["application"]["privateNote"] == "Call references."

        other_member = User(email="other@x.com", display_name="Other", role=UserRole.MEMBER, is_active=True)
        db.add(other_member)
        db.commit()
        app.dependency_overrides[require_current_user] = lambda: other_member

        # Another member cannot see the first member's private note.
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert detail["privateNote"] == ""
        await client.put(f"/applications/{application.id}/note", json={"note": "Review income source."})

        app.dependency_overrides[require_current_user] = lambda: first_member
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert detail["privateNote"] == "Call references."

    assert db.scalar(select(ApplicationNote).where(ApplicationNote.application_id == application.id)) is not None


@pytest.mark.anyio
async def test_committee_notes_are_shared_attributed_and_author_owned() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="committee-note@x.com", raw_hash="h1")
    first_member = db.scalar(select(User).where(User.email == "admin@x.com"))
    assert first_member is not None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        added = await client.post(
            f"/applications/{application.id}/committee-notes",
            json={"body": "Call references before the meeting."},
        )
        assert added.status_code == 200
        first_note = added.json()["application"]["committeeNotes"][0]
        assert first_note["authorName"] == first_member.display_name
        assert first_note["body"] == "Call references before the meeting."
        assert first_note["editableByMe"] is True
        assert first_note["createdAt"].endswith("Z")
        assert first_note["updatedAt"].endswith("Z")

        other_member = User(
            email="other@x.com",
            display_name="",
            role=UserRole.MEMBER,
            is_active=True,
        )
        db.add(other_member)
        db.commit()
        app.dependency_overrides[require_current_user] = lambda: other_member

        detail = (await client.get(f"/applications/{application.id}")).json()[
            "application"
        ]
        assert detail["committeeNotes"][0]["body"] == first_note["body"]
        assert detail["committeeNotes"][0]["editableByMe"] is False
        forbidden_update = await client.patch(
            f"/applications/{application.id}/committee-notes/{first_note['id']}",
            json={"body": "Overwrite another member's note."},
        )
        assert forbidden_update.status_code == 403

        second = await client.post(
            f"/applications/{application.id}/committee-notes",
            json={"body": "Interview availability confirmed."},
        )
        second_note = next(
            note
            for note in second.json()["application"]["committeeNotes"]
            if note["body"] == "Interview availability confirmed."
        )
        assert second_note["authorName"] == other_member.email
        assert second_note["editableByMe"] is True

        updated = await client.patch(
            f"/applications/{application.id}/committee-notes/{second_note['id']}",
            json={"body": "  Interview availability confirmed for Tuesday.  "},
        )
        updated_note = next(
            note
            for note in updated.json()["application"]["committeeNotes"]
            if note["id"] == second_note["id"]
        )
        assert updated_note["body"] == "Interview availability confirmed for Tuesday."
        assert (
            await client.delete(
                f"/applications/{application.id}/committee-notes/{second_note['id']}"
            )
        ).status_code == 200

    notes = list(db.scalars(select(ApplicationCommitteeNote)))
    assert len(notes) == 1
    assert notes[0].body == first_note["body"]


@pytest.mark.anyio
async def test_stars_are_scoped_to_the_current_member() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="star@x.com", raw_hash="h1")
    first_member = db.scalar(select(User).where(User.email == "admin@x.com"))
    assert first_member is not None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Star as the first member; the detail reflects it, idempotently.
        starred = await client.put(f"/applications/{application.id}/star")
        assert starred.status_code == 200
        assert starred.json()["application"]["starredByMe"] is True
        again = await client.put(f"/applications/{application.id}/star")
        assert again.json()["application"]["starredByMe"] is True

        other_member = User(email="other@x.com", display_name="Other", role=UserRole.MEMBER, is_active=True)
        db.add(other_member)
        db.commit()
        app.dependency_overrides[require_current_user] = lambda: other_member

        # Another member does not see the first member's star.
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert detail["starredByMe"] is False

    # Exactly one star row exists — the idempotent re-star did not duplicate it.
    assert (
        db.scalar(
            select(func.count())
            .select_from(ApplicationStar)
            .where(ApplicationStar.application_id == application.id)
        )
        == 1
    )


@pytest.mark.anyio
async def test_unstar_removes_the_star() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="unstar@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.put(f"/applications/{application.id}/star")
        removed = await client.delete(f"/applications/{application.id}/star")
        assert removed.status_code == 200
        assert removed.json()["application"]["starredByMe"] is False
        # Deleting again is a no-op, not an error.
        assert (await client.delete(f"/applications/{application.id}/star")).status_code == 200

    assert (
        db.scalar(select(ApplicationStar).where(ApplicationStar.application_id == application.id))
        is None
    )


@pytest.mark.anyio
async def test_shortlist_is_shared_between_members_and_removal_is_idempotent() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="shortlist@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        added = await client.put(f"/applications/{application.id}/shortlist")
        assert added.status_code == 200
        assert added.json()["application"]["shortlisted"] is True
        again = await client.put(f"/applications/{application.id}/shortlist")
        assert again.json()["application"]["shortlisted"] is True

        other_member = User(
            email="other@x.com",
            display_name="Other",
            role=UserRole.MEMBER,
            is_active=True,
        )
        db.add(other_member)
        db.commit()
        app.dependency_overrides[require_current_user] = lambda: other_member

        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert detail["shortlisted"] is True
        listing = (await client.get("/applications")).json()["applications"]
        assert listing[0]["shortlisted"] is True
        removed = await client.delete(f"/applications/{application.id}/shortlist")
        assert removed.json()["application"]["shortlisted"] is False
        assert (await client.delete(f"/applications/{application.id}/shortlist")).status_code == 200

    assert db.scalar(select(ApplicationShortlist)) is None


@pytest.mark.anyio
async def test_list_embeds_my_star_state_per_row() -> None:
    # The list is unpaginated; the client derives the favourites filter + count from
    # the per-row starredByMe flag, so that flag must be right for each row.
    app, db, _ = setup_app(role=UserRole.MEMBER)
    starred_app = add_eligible(db, email="fav@x.com", raw_hash="h1", name="Faved")
    plain_app = add_eligible(db, email="plain@x.com", raw_hash="h2", name="Plain")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.put(f"/applications/{starred_app.id}/star")

        listing = (await client.get("/applications")).json()
        by_id = {a["id"]: a for a in listing["applications"]}
        assert by_id[starred_app.id]["starredByMe"] is True
        assert by_id[plain_app.id]["starredByMe"] is False


@pytest.mark.anyio
async def test_list_and_detail_expose_opening_participation() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="opening@x.com", raw_hash="h1", active=False)
    today = date.today()
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=125_000,
        application_open_date=today - timedelta(days=1),
        application_close_date=today + timedelta(days=10),
        move_in_date=today + timedelta(days=30),
        published_at=datetime.now(UTC),
    )
    db.add(opening)
    db.flush()
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=opening.id,
            applied_at=datetime.now(UTC),
        )
    )
    submitted_at = datetime(2026, 2, 3, 4, 5, tzinfo=UTC)
    application.submitted_at = submitted_at
    db.add(
        ApplicationVersion(
            application_id=application.id,
            answers=application.raw_row,
            normalized=application.normalized,
            selected_opening_ids=[opening.id],
            content_hash=application.raw_row_hash,
            submitted_at=submitted_at,
        )
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        listing = (await client.get("/applications")).json()
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]

    assert listing["openings"][0]["id"] == opening.id
    assert listing["applications"][0]["openingIds"] == [opening.id]
    assert "submittedAt" not in listing["applications"][0]
    assert "submissionVersionCount" not in listing["applications"][0]
    assert detail["openingIds"] == [opening.id]
    assert detail["firstSubmittedAt"] == "2026-02-03T04:05:00+00:00"
    assert detail["lastSubmittedAt"] == "2026-02-03T04:05:00+00:00"
    assert "declarationAcceptedAt" not in detail
    assert detail["submissionVersionCount"] == 1
