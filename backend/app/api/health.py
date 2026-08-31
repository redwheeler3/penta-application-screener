from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.db.models import User
from app.db.session import get_db
from app.schemas.base import ResponseModel

router = APIRouter(tags=["health"])


class HealthResponse(ResponseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    try:
        db.execute(select(User.id).limit(1)).first()
    except SQLAlchemyError:
        raise Problem(
            "database_unavailable",
            detail="The application database is unavailable.",
        ) from None
    return HealthResponse(status="ok")
