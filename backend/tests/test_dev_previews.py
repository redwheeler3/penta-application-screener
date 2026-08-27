import pytest
from httpx2 import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.mark.anyio
async def test_email_preview_renders_every_template_without_real_addresses() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        email_delivery_mode="capture",
        _env_file=None,
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/dev/previews/emails")

    assert response.status_code == 200
    previews = response.json()
    assert [preview["key"] for preview in previews] == [
        "application-saved",
        "application-submitted",
        "applicant-access",
        "committee-access",
        "email-change-confirmation",
        "email-change-notice",
        "application-deleted",
        "application-unavailable",
        "application-unsuccessful",
    ]
    assert all(preview["subject"] and "PENTA HOUSING CO-OP" in preview["html"] for preview in previews)
    assert "jeffo.net" not in response.text
    assert "pentacoop.com#" not in response.text


@pytest.mark.anyio
async def test_email_preview_is_not_available_in_production() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        email_delivery_mode="production",
        _env_file=None,
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/dev/previews/emails")

    assert response.status_code == 404
