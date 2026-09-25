from datetime import datetime

from app.schemas.base import ResponseModel


class PublicEmailDeliveryStatus(ResponseModel):
    delayed: bool


class SocketLabsQueueStatusOut(ResponseModel):
    available: bool
    delayed: bool
    queued_count: int | None = None
    oldest_queued_at: datetime | None = None
    retrieved_at: datetime | None = None
