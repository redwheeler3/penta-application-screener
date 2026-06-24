import json

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.mock_provider import MockProvider
from app.ai.schemas import FlagCategory, FlagSeverity, QualityFlag, QualityFlagReport
from app.api.dependencies import require_current_user
from app.api.quality_flags import get_ai_provider
from app.db.models import Application, ApplicationStatus, Base, User, UserRole
from app.db.session import get_db
from app.main import create_app


async def run_and_summarize(client: AsyncClient) -> dict:
    """POST the streaming run and return the final summary line as a dict."""
    response = await client.post("/quality-flags/run")
    assert response.status_code == 200
    summary = None
    for line in response.text.splitlines():
        if line.strip():
            event = json.loads(line)
            if event.get("type") == "summary":
                summary = event
    assert summary is not None, "stream did not include a summary line"
    return summary


def setup_app(role: UserRole | None) -> tuple:
    """Build an app wired to a shared in-memory DB, optionally authed as a user
    of the given role (None = anonymous). Returns (app, session, provider)."""
    # StaticPool so every connection shares one in-memory DB (otherwise each new
    # connection — e.g. a lazy attribute reload — sees an empty database).
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()

    user = None
    if role is not None:
        user = User(email="admin@x.com", display_name="Admin", role=role, is_active=True)
        db.add(user)
        db.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    if user is not None:
        app.dependency_overrides[require_current_user] = lambda: user

    provider = MockProvider()
    app.dependency_overrides[get_ai_provider] = lambda: provider
    return app, db, provider


def add_eligible(
    db: Session, *, email: str, raw_hash: str, name: str = "Test"
) -> Application:
    app = Application(
        primary_email=email,
        applicant_name=name,
        raw_row={},
        raw_row_hash=raw_hash,
        # The name is surfaced in the prompt, so a distinct name lets a test
        # route a specific verdict to this application regardless of the order
        # concurrent screening calls complete in.
        normalized={"applicant_name": name},
        status=ApplicationStatus.ELIGIBLE,
        hard_filter_reasons=[],
    )
    db.add(app)
    db.commit()
    return app


@pytest.mark.anyio
async def test_run_requires_login() -> None:
    app, _, _ = setup_app(role=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/quality-flags/run")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_member_can_run_quality_flags() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="member@x.com", raw_hash="h1")
    provider.queue(QualityFlagReport(flags=[]))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        summary = await run_and_summarize(client)

    assert summary["analyzed"] == 1
    assert summary["cached"] == 0
    assert len(provider.calls) == 1


@pytest.mark.anyio
async def test_admin_run_analyzes_eligible_and_reports() -> None:
    app, db, provider = setup_app(role=UserRole.ADMIN)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    add_eligible(db, email="b@x.com", raw_hash="h2")
    # One clean, one flagged.
    provider.queue(QualityFlagReport(flags=[]))
    provider.queue(
        QualityFlagReport(
            flags=[
                QualityFlag(
                    category=FlagCategory.MINIMAL_ESSAY,
                    severity=FlagSeverity.INFO,
                    summary="Essay is a single word.",
                    evidence="Why a co-op: 'housing'",
                )
            ]
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        summary = await run_and_summarize(client)

    assert summary["analyzed"] == 2
    assert summary["cached"] == 0
    assert summary["flagged"] == 1


@pytest.mark.anyio
async def test_fully_cached_rerun_is_blocked() -> None:
    # Once every applicant is cached, re-screening is a $0 no-op, so the endpoint
    # blocks it (409) — symmetric with the Rank chain's pool gate. The UI turns
    # this into an "already up to date" toast.
    app, db, provider = setup_app(role=UserRole.ADMIN)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    add_eligible(db, email="b@x.com", raw_hash="h2")
    provider.queue(QualityFlagReport(flags=[]))
    provider.queue(QualityFlagReport(flags=[]))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await run_and_summarize(client)
        assert first["analyzed"] == 2
        assert first["totalCostUsd"] > 0  # real calls cost money

        # Nothing uncached now → blocked.
        assert (await client.post("/quality-flags/run")).status_code == 409


@pytest.mark.anyio
async def test_partial_cache_run_counts_only_uncached_cost() -> None:
    # A run with a mix of cached and new applicants must report only the NEW
    # ones' cost — a cache hit carries its original first-run cost for auditing,
    # but that is not money spent now. (Regression: the tally summed cached cost.)
    app, db, provider = setup_app(role=UserRole.ADMIN)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    add_eligible(db, email="b@x.com", raw_hash="h2")
    provider.queue(QualityFlagReport(flags=[]))
    provider.queue(QualityFlagReport(flags=[]))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await run_and_summarize(client)
        assert first["analyzed"] == 2
        first_cost = first["totalCostUsd"]

        # Add one new applicant and re-run: 2 cached + 1 new. The run proceeds
        # (one uncached), and the total reflects only that one call — not the two
        # cached results' stored cost.
        add_eligible(db, email="c@x.com", raw_hash="h3")
        provider.queue(QualityFlagReport(flags=[]))
        second = await run_and_summarize(client)
        assert second["analyzed"] == 1
        assert second["cached"] == 2
        assert 0 < second["totalCostUsd"] < first_cost


@pytest.mark.anyio
async def test_ai_flag_sets_needs_review_status_and_filter() -> None:
    app, db, provider = setup_app(role=UserRole.ADMIN)
    add_eligible(db, email="flag@x.com", raw_hash="h1", name="Flagged Applicant")
    add_eligible(db, email="clean@x.com", raw_hash="h2", name="Clean Applicant")
    # Bind verdicts to applications by name: the screening pass runs concurrently
    # so results don't complete in submission order.
    provider.route(
        "Flagged Applicant",
        QualityFlagReport(
            flags=[
                QualityFlag(
                    category=FlagCategory.PET_POLICY,
                    severity=FlagSeverity.NOTABLE,
                    summary="Too many pets.",
                    evidence="pets",
                )
            ]
        ),
    )
    provider.route("Clean Applicant", QualityFlagReport(flags=[]))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await run_and_summarize(client)

        all_apps = (await client.get("/applications")).json()["applications"]
        by_email = {a["primaryEmail"]: a for a in all_apps}
        # AI flag -> ineligible / ai (the needs-review bucket); flags recorded.
        assert by_email["flag@x.com"]["status"] == "ineligible"
        assert by_email["flag@x.com"]["statusSource"] == "ai"
        assert by_email["flag@x.com"]["flagCount"] == 1
        assert by_email["flag@x.com"]["flagCategories"] == ["pet_policy"]
        # Clean -> stays eligible / untouched.
        assert by_email["clean@x.com"]["status"] == "eligible"
        assert by_email["clean@x.com"]["statusSource"] == "untouched"
        assert by_email["clean@x.com"]["flagCount"] == 0

        # Needs-review queue is the AI-source bucket.
        needs_review = await client.get("/applications", params={"status_source": "ai"})
        body = needs_review.json()
        assert body["total"] == 1
        assert body["applications"][0]["primaryEmail"] == "flag@x.com"

        dashboard = (await client.get("/dashboard")).json()
        # "Needs review" is the client's label for the ai source bucket.
        assert dashboard["counts"]["source"]["ai"] == 1
        assert dashboard["counts"]["status"]["ineligible"] == 1


@pytest.mark.anyio
async def test_raw_row_and_narrative_visible_to_members() -> None:
    """The raw source row and AI narrative are shown to any committee member,
    not only admins — members are trusted screeners.
    """
    app, db, provider = setup_app(role=UserRole.MEMBER)
    flagged = add_eligible(db, email="flag@x.com", raw_hash="h1")
    provider.queue(
        QualityFlagReport(
            flags=[
                QualityFlag(
                    category=FlagCategory.PET_POLICY,
                    severity=FlagSeverity.NOTABLE,
                    summary="Too many pets.",
                    evidence="pets",
                )
            ]
        ),
        narrative="Checking pets: a hamster is outside the allowed categories.",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await run_and_summarize(client)

        member_detail = (await client.get(f"/applications/{flagged.id}")).json()[
            "application"
        ]
        assert member_detail["aiNarrative"] == (
            "Checking pets: a hamster is outside the allowed categories."
        )
        assert "rawRow" in member_detail


@pytest.mark.anyio
async def test_facet_counts_reflect_cross_group_filter() -> None:
    app, db, provider = setup_app(role=UserRole.ADMIN)
    add_eligible(db, email="flag@x.com", raw_hash="h1", name="Flagged Applicant")
    add_eligible(db, email="clean@x.com", raw_hash="h2", name="Clean Applicant")
    provider.route(
        "Flagged Applicant",
        QualityFlagReport(
            flags=[
                QualityFlag(
                    category=FlagCategory.PET_POLICY,
                    severity=FlagSeverity.NOTABLE,
                    summary="Too many pets.",
                    evidence="pets",
                )
            ]
        ),
    )
    provider.route("Clean Applicant", QualityFlagReport(flags=[]))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await run_and_summarize(client)

        # Unfiltered: facets show the full population.
        facets = (await client.get("/applications")).json()["facets"]
        assert facets["status"] == {"eligible": 1, "ineligible": 1}
        assert facets["source"]["rules"] == 0
        assert facets["source"]["ai"] == 1

        # Filter to Eligible -> the source facet must drop the AI exclusion to 0
        # (there are no eligible-AND-ai rows). This is the bug being fixed.
        eligible = (await client.get("/applications", params={"status": "eligible"})).json()
        assert eligible["facets"]["source"]["ai"] == 0
        assert eligible["facets"]["source"]["untouched"] == 1
        # The status facet ignores its own filter, so it still shows both.
        assert eligible["facets"]["status"] == {"eligible": 1, "ineligible": 1}


@pytest.mark.anyio
async def test_human_override_is_sticky_and_snapshots_fingerprint() -> None:
    app, db, provider = setup_app(role=UserRole.ADMIN)
    flagged = add_eligible(db, email="flag@x.com", raw_hash="h1")
    provider.queue(
        QualityFlagReport(
            flags=[
                QualityFlag(
                    category=FlagCategory.PET_POLICY,
                    severity=FlagSeverity.NOTABLE,
                    summary="Too many pets.",
                    evidence="pets",
                )
            ]
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await run_and_summarize(client)
        # AI flagged it -> ineligible/ai.
        detail = (await client.get(f"/applications/{flagged.id}")).json()["application"]
        assert detail["status"] == "ineligible"

        # Human restores to eligible.
        patched = (
            await client.patch(
                f"/applications/{flagged.id}/status", json={"status": "eligible"}
            )
        ).json()["application"]
        assert patched["status"] == "eligible"
        assert patched["statusSource"] == "human"
        assert patched["stale"] is False
        # Flags are preserved through the override.
        assert patched["flagCount"] == 1

        # A re-run must not flip the human status or go stale, even though the
        # cached result still flows through the status hook. The pool must change
        # for a re-run to be allowed at all (the no-op gate), so add a new
        # applicant to trigger it; the human-overridden one stays cached and its
        # hook must respect the sticky human status.
        add_eligible(db, email="new@x.com", raw_hash="h2")
        provider.queue(QualityFlagReport(flags=[]))  # for the new applicant only
        await run_and_summarize(client)
        detail = (await client.get(f"/applications/{flagged.id}")).json()["application"]
        assert detail["status"] == "eligible"
        assert detail["statusSource"] == "human"
        assert detail["stale"] is False


@pytest.mark.anyio
async def test_clear_override_restores_machine_status() -> None:
    """Deleting a human override hands the decision back to the machine, which
    recomputes from the current findings (here: the AI flag -> ineligible/ai)."""
    app, db, provider = setup_app(role=UserRole.ADMIN)
    flagged = add_eligible(db, email="flag@x.com", raw_hash="h1")
    provider.queue(
        QualityFlagReport(
            flags=[
                QualityFlag(
                    category=FlagCategory.PET_POLICY,
                    severity=FlagSeverity.NOTABLE,
                    summary="Too many pets.",
                    evidence="pets",
                )
            ]
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await run_and_summarize(client)
        # Human overrides the AI flag back to eligible.
        patched = (
            await client.patch(
                f"/applications/{flagged.id}/status", json={"status": "eligible"}
            )
        ).json()["application"]
        assert patched["statusSource"] == "human"
        # The detail payload exposes what Automatic would decide.
        assert patched["autoStatus"] == "ineligible"
        assert patched["autoStatusSource"] == "ai"

        # Clearing the override recomputes from the still-present AI flag.
        cleared = (
            await client.delete(f"/applications/{flagged.id}/status")
        ).json()["application"]
        assert cleared["status"] == "ineligible"
        assert cleared["statusSource"] == "ai"
        assert cleared["stale"] is False
        assert cleared["flagCount"] == 1


@pytest.mark.anyio
async def test_clear_override_without_override_is_noop() -> None:
    """DELETE on a machine-owned status is idempotent and leaves it untouched."""
    app, db, _ = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.delete(f"/applications/{application.id}/status")
        assert response.status_code == 200
        cleared = response.json()["application"]
        assert cleared["status"] == "eligible"
        assert cleared["statusSource"] == "untouched"


@pytest.mark.anyio
async def test_member_can_override_status() -> None:
    """Status override is open to any committee member, not only admins."""
    app, db, _ = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.patch(
            f"/applications/{application.id}/status", json={"status": "ineligible"}
        )
        assert response.status_code == 200
        patched = response.json()["application"]
        assert patched["status"] == "ineligible"
        assert patched["statusSource"] == "human"


@pytest.mark.anyio
async def test_flag_count_null_before_run() -> None:
    app, db, _ = setup_app(role=UserRole.ADMIN)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        body = (await client.get("/applications")).json()
    # No quality-flag pass yet -> flagCount is null (unknown), not 0.
    assert body["applications"][0]["flagCount"] is None


@pytest.mark.anyio
async def test_estimate_reports_cap_and_within_cap() -> None:
    app, db, _ = setup_app(role=UserRole.ADMIN)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/quality-flags/estimate")

    assert response.status_code == 200
    body = response.json()
    assert body["to_analyze"] == 1
    assert body["cap_usd"] == 0.5
    assert body["within_cap"] is True
