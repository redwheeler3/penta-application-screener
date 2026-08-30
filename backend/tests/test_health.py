import pytest
from httpx2 import ASGITransport, AsyncClient

from tests.app_support import shared_test_app


@pytest.mark.anyio
async def test_health_check() -> None:
    transport = ASGITransport(app=shared_test_app())

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
