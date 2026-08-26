"""Response shapes for opportunistic lifecycle maintenance."""

from app.schemas.base import ResponseModel


class MaintenanceResponse(ResponseModel):
    unsuccessful_notices_sent: int
