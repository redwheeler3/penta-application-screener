"""Read-only SocketLabs plan usage for administrator send previews."""

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.time import as_utc

USAGE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class SocketLabsUsage:
    retrieved_at: datetime
    billing_period_start: datetime
    billing_period_end: datetime
    messages_used: int
    message_allowance: int
    messages_used_percent: float
    allow_overages: bool


class SocketLabsUsageReader(Protocol):
    def fetch(self) -> SocketLabsUsage | None: ...


class UnavailableSocketLabsUsageReader:
    def fetch(self) -> None:
        return None


class SocketLabsUsageClient:
    def __init__(self, client: httpx.Client, *, base_url: str, server_id: int, api_key: str) -> None:
        self.client = client
        self.url = f"{base_url.rstrip('/')}/v2/servers/{server_id}/subscription/usage-summary"
        self.api_key = api_key

    def fetch(self) -> SocketLabsUsage | None:
        try:
            response = self.client.get(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            payload = response.json()["data"]
            usage = payload["usage"]
            allowance = payload["allowance"]
            return SocketLabsUsage(
                retrieved_at=as_utc(datetime.now().astimezone()),
                billing_period_start=as_utc(datetime.fromisoformat(payload["billingPeriodStartDateTime"])),
                billing_period_end=as_utc(datetime.fromisoformat(payload["billingPeriodEndDateTime"])),
                messages_used=int(usage["messagesUsed"]),
                message_allowance=int(allowance["messageAllowance"]),
                messages_used_percent=float(usage["messagesUsedPercent"]),
                allow_overages=bool(payload["plan"]["allowOverages"]),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None


def build_socketlabs_usage_reader(settings: Settings) -> SocketLabsUsageReader:
    if not settings.email_delivery_enabled:
        return UnavailableSocketLabsUsageReader()
    try:
        server_id = int(settings.socketlabs_server_id)
    except ValueError:
        return UnavailableSocketLabsUsageReader()
    if server_id <= 0 or not settings.socketlabs_injection_api_key:
        return UnavailableSocketLabsUsageReader()
    return SocketLabsUsageClient(
        httpx.Client(timeout=USAGE_TIMEOUT_SECONDS),
        base_url=settings.socketlabs_api_base,
        server_id=server_id,
        api_key=settings.socketlabs_injection_api_key,
    )


@lru_cache
def get_socketlabs_usage_reader() -> SocketLabsUsageReader:
    return build_socketlabs_usage_reader(get_settings())
