import pytest
from httpx2 import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.anyio
async def test_me_returns_no_user_when_logged_out() -> None:
    transport = ASGITransport(app=create_app())

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {"user": None}

