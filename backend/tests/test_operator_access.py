"""Engineering tools are admin-only; versioned fixture edits stay local."""

from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.db.models import UserRole
from app.evals import case_store
from app.schemas.settings import AppSettings
from app.services.auth.authority import require_admin_write
from app.services.settings import save_app_settings
from tests.ranking_support import add_eligible
from tests.test_evals_api import setup_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/evals/catalog"), ("GET", "/evals/invariants"), ("GET", "/evals/cases/scoring"),
    ("GET", "/evals/judge-backgrounds"), ("GET", "/evals/last-run?keys=scoring"),
    ("POST", "/evals/scoring"), ("POST", "/evals/judge"), ("POST", "/evals/baseline"),
    ("PUT", "/evals/cases/scoring"), ("PUT", "/evals/judge-backgrounds/scoring"),
    ("GET", "/observability/cost"), ("GET", "/observability/metrics"), ("GET", "/observability/last-runs"),
    ("GET", "/ranking/analyses/1/fan-out-audit"), ("GET", "/ranking/analyses/1/match-audit"),
    ("GET", "/ranking/analyses/1/decompose-audit"), ("GET", "/ranking/analyses/1/consolidate-audit"),
])
async def test_member_cannot_use_operator_routes(method, path):
    app, _db, provider = setup_app(UserRole.MEMBER)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.request(method, path, json={"case": {}, "background": "Synthetic brief"})
    assert response.status_code == 403
    assert not provider.calls


@pytest.mark.anyio
async def test_member_can_still_read_ordinary_ranking_views():
    from sqlalchemy import select

    from app.db.models import User
    from app.services.ranking.analysis import create_analysis
    from tests.application_support import current_opening_id
    from tests.ranking_support import a_pattern_report

    app, db, _provider = setup_app(UserRole.MEMBER)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    create_analysis(db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
        report=a_pattern_report(), narrative=None, inputs_fingerprint="synthetic")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.get("/ranking/current")).status_code == 200
        assert (await client.get("/ranking/board")).status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.ADMIN])
async def test_ranking_views_omit_narrative_and_only_admins_can_read_its_trace(role):
    from sqlalchemy import select

    from app.db.models import User
    from app.services.ranking.analysis import create_analysis
    from tests.application_support import current_opening_id
    from tests.ranking_support import a_pattern_report

    app, db, _provider = setup_app(role)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    create_analysis(db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
        report=a_pattern_report(), narrative="Synthetic operator reasoning", inputs_fingerprint="synthetic")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        current = (await client.get("/ranking/current")).json()
        board = (await client.get("/ranking/board")).json()
        trace = await client.get(f"/ranking/analyses/{current['analysisId']}/fan-out-audit")
        if role == UserRole.ADMIN:
            assert trace.json()["narrative"] == "Synthetic operator reasoning"
        else:
            assert trace.status_code == 403
    assert "discoveryNarrative" not in current
    assert "discoveryNarrative" not in board["run"]
    assert current["dimensions"]


@pytest.mark.anyio
async def test_trace_uses_the_viewed_analysis_and_checks_its_opening():
    from datetime import UTC, date, datetime, timedelta

    from sqlalchemy import select

    from app.db.models import ApplicationParticipation, Opening, User
    from app.services.ranking.analysis import create_analysis
    from tests.application_support import current_opening_id
    from tests.ranking_support import a_pattern_report

    app, db, _provider = setup_app(UserRole.ADMIN)
    applicant = add_eligible(db, email="synthetic@example.test", raw_hash="synthetic")
    opening_id = current_opening_id(db)
    user = db.scalar(select(User))
    old = create_analysis(db, user=user, opening_id=opening_id, report=a_pattern_report(),
        narrative="Earlier synthetic trace", inputs_fingerprint="earlier")
    latest = create_analysis(db, user=user, opening_id=opening_id, report=a_pattern_report(),
        narrative="Latest synthetic trace", inputs_fingerprint="latest")
    other = Opening(unit_size_bedrooms=1, housing_charge_cents=100000, application_open_date=date.today(),
        application_close_date=date.today() + timedelta(days=10), move_in_date=date.today() + timedelta(days=20),
        published_at=datetime.now(UTC))
    db.add(other)
    db.flush()
    db.add(ApplicationParticipation(application_id=applicant.id, opening_id=other.id, applied_at=datetime.now(UTC)))
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        for analysis, narrative in [(old, "Earlier synthetic trace"), (latest, "Latest synthetic trace")]:
            response = await client.get(f"/ranking/analyses/{analysis.id}/fan-out-audit?opening_id={opening_id}")
            assert response.status_code == 200
            assert response.json()["analysisId"] == analysis.id
            assert response.json()["narrative"] == narrative
        for audit in ("fan-out", "match", "decompose", "consolidate"):
            response = await client.get(f"/ranking/analyses/{old.id}/{audit}-audit?opening_id={other.id}")
            assert response.status_code == 404


@pytest.mark.parametrize(("frontend", "fly", "editable"), [
    ("http://localhost:5173", "", True), ("http://127.0.0.1:5173", "", True),
    ("http://[::1]:5173", "", True), ("https://hosted.example.com", "", False),
    ("http://localhost:5173", "penta-hosted", False), ("http://remote.example.com", "", False),
])
def test_fixture_editing_is_a_local_runtime_capability(frontend, fly, editable):
    assert Settings(frontend_url=frontend, fly_app_name=fly).eval_fixture_editing_enabled is editable


@pytest.mark.anyio
@pytest.mark.parametrize(("path", "body"), [
    ("/evals/cases/scoring", {"case": {"key": "synthetic"}}),
    ("/evals/judge-backgrounds/scoring", {"background": "Synthetic brief"}),
    ("/evals/baseline", None),
])
async def test_hosted_admin_cannot_modify_versioned_files(monkeypatch, path, body):
    app, _db, _provider = setup_app()
    hosted = Settings(frontend_url="https://hosted.example.com")
    monkeypatch.setattr("app.api.evals._shared.get_settings", lambda: hosted)
    monkeypatch.setattr("app.api.evals.catalog.get_settings", lambda: hosted)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        catalog = await client.get("/evals/catalog")
        response = await client.request("POST" if body is None else "PUT", path, json=body)
    assert catalog.json()["fixtureEditingEnabled"] is False
    assert response.status_code == 403
    assert response.json()["code"] == "eval_fixtures_read_only"


@pytest.mark.anyio
async def test_fixture_write_rechecks_admin_before_touching_the_file(monkeypatch):
    from sqlalchemy import select

    from app.db.models import User

    app, _db, _provider = setup_app()
    case = case_store.list_cases("scoring")[0]
    touched = Mock()
    monkeypatch.setattr("app.api.evals.cases.save_case", touched)

    def revoke_then_check(db, actor_id):
        db.scalar(select(User)).role = UserRole.MEMBER
        db.commit()
        require_admin_write(db, actor_id)

    monkeypatch.setattr("app.api.evals._shared.require_admin_write", revoke_then_check)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.put("/evals/cases/scoring", json={"case": case})
    assert response.status_code == 403
    touched.assert_not_called()


@pytest.mark.anyio
async def test_hosted_admin_evals_remain_uncapped_and_read_committed_cases(monkeypatch):
    app, db, provider = setup_app()
    hosted = Settings(frontend_url="https://hosted.example.com")
    monkeypatch.setattr("app.api.evals._shared.get_settings", lambda: hosted)
    settings = AppSettings()
    settings.ai.spending_cap_usd = 0
    save_app_settings(db, settings)
    key = case_store.list_cases("scoring")[0]["key"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/evals/scoring?case={key}")
    assert response.status_code == 200
    assert provider.calls
