import pytest
from httpx2 import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.anyio
async def test_dashboard_requires_login() -> None:
    transport = ASGITransport(app=create_app())

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/dashboard")

    assert response.status_code == 401

