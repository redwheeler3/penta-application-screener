from datetime import UTC, datetime

import httpx

from app.services.socketlabs_usage import SocketLabsUsageClient


def test_usage_client_reads_documented_socketlabs_summary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/servers/123/subscription/usage-summary"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "data": {
                    "billingPeriodStartDateTime": "2026-08-01T00:00:00+00:00",
                    "billingPeriodEndDateTime": "2026-09-01T00:00:00+00:00",
                    "plan": {"allowOverages": False},
                    "usage": {"messagesUsed": 1200, "messagesUsedPercent": 60},
                    "allowance": {"messageAllowance": 2000},
                }
            },
        )

    client = SocketLabsUsageClient(
        httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://api.socketlabs.com",
        server_id=123,
        api_key="secret",
    )

    result = client.fetch()

    assert result is not None
    assert result.billing_period_start == datetime(2026, 8, 1, tzinfo=UTC)
    assert result.messages_used == 1200
    assert result.message_allowance == 2000
    assert result.allow_overages is False


def test_usage_client_returns_unknown_on_provider_or_shape_failure() -> None:
    client = SocketLabsUsageClient(
        httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(503))),
        base_url="https://api.socketlabs.com",
        server_id=123,
        api_key="secret",
    )

    assert client.fetch() is None
