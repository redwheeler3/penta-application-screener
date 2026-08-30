import pytest
from httpx2 import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from tests.app_support import shared_test_app


@pytest.mark.anyio
async def test_email_preview_renders_every_template_without_real_addresses() -> None:
    app = shared_test_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        email_delivery_mode="capture",
        _env_file=None,
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/dev/previews/emails",
            headers={"Origin": "http://localhost:5173"},
        )

    assert response.status_code == 200
    assert response.headers["X-Preview-Process"].isdigit()
    assert "X-Preview-Process" in response.headers["Access-Control-Expose-Headers"]
    previews = response.json()
    assert [preview["key"] for preview in previews] == [
        "application-saved",
        "application-submitted",
        "applicant-access",
        "committee-access",
        "email-change-confirmation",
        "email-change-notice",
        "application-unavailable",
        "application-unsuccessful",
        "vacancy-opening-list-only",
        "vacancy-opening-application-only",
        "vacancy-opening-overlap",
    ]
    assert all(preview["subject"] and "PENTA HOUSING CO-OP" in preview["html"] for preview in previews)
    assert "jeffo.net" not in response.text
    assert "pentacoop.com#" not in response.text
    assert "removed you from the vacancy notification list" in response.text
    assert "https://www.pentacoop.com/apply.html" in response.text
    submitted = next(preview for preview in previews if preview["key"] == "application-submitted")
    assert "2-bedroom home" in submitted["html"]
    assert "3-bedroom home" in submitted["html"]
    assert "September 15, 2026" in submitted["html"]
    assert "November 1, 2026" in submitted["html"]
    assert "Whether or not you&#x27;re shortlisted" in submitted["html"]


@pytest.mark.anyio
async def test_email_preview_is_not_available_in_production() -> None:
    app = shared_test_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        email_delivery_mode="production",
        _env_file=None,
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/dev/previews/emails")

    assert response.status_code == 404
