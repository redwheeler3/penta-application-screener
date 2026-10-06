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
    ("GET", "/ranking/current/fan-out-audit"), ("GET", "/ranking/current/match-audit"),
    ("GET", "/ranking/current/decompose-audit"), ("GET", "/ranking/current/consolidate-audit"),
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
async def test_ranking_views_only_include_operator_narrative_for_admins(role):
    from sqlalchemy import select

    from app.db.models import User
    from app.services.ranking.analysis import create_analysis
    from tests.application_support import current_opening_id
    from tests.ranking_support import a_pattern_report

    app, db, _provider = setup_app(role)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    create_analysis(db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
        report=a_pattern_report(), narrative="Synthetic operator reasoning", inputs_fingerprint="synthetic")
    expected = "Synthetic operator reasoning" if role == UserRole.ADMIN else None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        current = (await client.get("/ranking/current")).json()
        board = (await client.get("/ranking/board")).json()
    assert current["discoveryNarrative"] == expected
    assert board["run"]["discoveryNarrative"] == expected
    assert current["dimensions"]


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
