from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api.applications import router as applications_router
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.evals import router as evals_router
from app.api.health import router as health_router
from app.api.problems import Problem
from app.api.ranking import router as ranking_router
from app.api.screening import router as screening_router
from app.api.settings import router as settings_router
from app.api.sync import router as sync_router
from app.core.config import get_settings

PROBLEM_JSON = "application/problem+json"


def _problem_response(body: dict, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_JSON)


def register_error_handlers(app: FastAPI) -> None:
    """Render every error as RFC 9457 problem+json — one machine-readable shape.

    Two handlers: our own ``Problem`` (the app's raised errors) and FastAPI's
    ``RequestValidationError`` (malformed/invalid request bodies and params). The
    second is what keeps framework-generated 422s from sitting in FastAPI's default
    ``{"detail": [...]}`` shape beside our problems — without it the contract leaks.
    """

    @app.exception_handler(Problem)
    async def handle_problem(request: Request, exc: Problem) -> JSONResponse:
        return _problem_response(exc.to_dict(instance=request.url.path), exc.status)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        problem = Problem(
            "validation_error",
            detail="One or more request fields are invalid.",
            # The Pydantic error list as an extension member, JSON-safe.
            errors=jsonable_encoder(exc.errors()),
        )
        return _problem_response(problem.to_dict(instance=request.url.path), problem.status)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Penta Application Screener API")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        same_site="lax",
        https_only=False,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(applications_router)
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(evals_router)
    app.include_router(health_router)
    app.include_router(screening_router)
    app.include_router(ranking_router)
    app.include_router(settings_router)
    app.include_router(sync_router)
    return app


app = create_app()
