from fastapi import APIRouter

from app.schemas.base import ResponseModel

router = APIRouter(tags=["health"])


class HealthResponse(ResponseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")
