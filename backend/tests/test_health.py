from unittest.mock import Mock

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import get_db
from tests.app_support import shared_test_app


@pytest.mark.anyio
async def test_health_check() -> None:
    app = shared_test_app()
    db = Mock(spec=Session)
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    db.execute.assert_called_once()


@pytest.mark.anyio
async def test_health_check_reports_an_unavailable_database() -> None:
    app = shared_test_app()
    db = Mock(spec=Session)
    db.execute.side_effect = OperationalError("database probe", {}, Exception("offline"))
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "type": "/problems/database-unavailable",
        "title": "Database unavailable",
        "status": 503,
        "code": "database_unavailable",
        "instance": "/health",
        "detail": "The application database is unavailable.",
    }
