"""Privacy-minimal public email delivery health."""

from fastapi import APIRouter, Depends

from app.schemas.email_delivery import PublicEmailDeliveryStatus
from app.services.socketlabs_queue import (
    SocketLabsQueueReader,
    get_socketlabs_queue_reader,
)

router = APIRouter(prefix="/email-delivery", tags=["email delivery"])


@router.get("/status", response_model=PublicEmailDeliveryStatus)
def read_public_email_delivery_status(
    reader: SocketLabsQueueReader = Depends(get_socketlabs_queue_reader),
) -> PublicEmailDeliveryStatus:
    status = reader.cached()
    return PublicEmailDeliveryStatus(
        available=status is not None,
        delayed=status.delayed if status else False,
    )


@router.post("/status/refresh", response_model=PublicEmailDeliveryStatus)
def refresh_public_email_delivery_status(
    reader: SocketLabsQueueReader = Depends(get_socketlabs_queue_reader),
) -> PublicEmailDeliveryStatus:
    status = reader.fetch()
    return PublicEmailDeliveryStatus(
        available=status is not None,
        delayed=status.delayed if status else False,
    )
