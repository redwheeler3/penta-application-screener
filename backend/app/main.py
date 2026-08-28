from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTasks
from starlette.middleware.sessions import SessionMiddleware

from app.api.allowlist import router as allowlist_router
from app.api.applicant import router as applicant_router
from app.api.applications import router as applications_router
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.dev_previews import router as dev_previews_router
from app.api.evals import router as evals_router
from app.api.feedback import router as feedback_router
from app.api.health import router as health_router
from app.api.observability import router as observability_router
from app.api.openings import router as openings_router
from app.api.passwordless_auth import router as passwordless_auth_router
from app.api.ranking import router as ranking_router
from app.api.screening import router as screening_router
from app.api.settings import router as settings_router
from app.api.settings import rules_router as eligibility_rules_router
from app.core.config import get_settings
from app.core.problems import Problem
from app.services.maintenance import run_due_maintenance

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """On startup, ensure the bootstrap admins are on the allowlist. Done here (not at
    import) so tests with their own DB aren't seeded from the real file; idempotent, so
    repeated starts are harmless."""
    from app.db.session import SessionLocal
    from app.services.allowlist import seed_initial_admins

    db = SessionLocal()
    try:
        seed_initial_admins(db)
    finally:
        db.close()
    yield


def create_app(*, maintenance_task: Callable[[], None] | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Penta Application Screener API", lifespan=lifespan)
    # Authlib uses this signed cookie only while a browser completes Google OIDC. Successful
    # Google and email sign-ins both issue the same revocable BrowserSession cookie.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        same_site="lax",
        https_only=settings.oauth_state_cookie_secure,
        max_age=10 * 60,
    )
    # CORS is only load-bearing in the two-origin DEV setup (Vite :5173 → API :8000).
    # In the single-origin prod deploy (FastAPI serves the bundle) requests are same-origin,
    # so this allowance is simply never exercised. Driven off `frontend_url` so it's correct
    # in both without a hardcoded localhost.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list({settings.frontend_url, settings.applicant_frontend_url}),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Preview-Process"],
    )

    @app.middleware("http")
    async def prevent_applicant_data_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/applicant"):
            response.headers["Cache-Control"] = "no-store"
        if maintenance_task is not None and _triggers_maintenance(request):
            tasks = BackgroundTasks()
            if response.background is not None:
                tasks.add_task(response.background)
            tasks.add_task(maintenance_task)
            response.background = tasks
        return response

    register_error_handlers(app)
    app.include_router(allowlist_router)
    app.include_router(applicant_router)
    app.include_router(applications_router)
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(dev_previews_router)
    app.include_router(evals_router)
    app.include_router(feedback_router)
    app.include_router(health_router)
    app.include_router(observability_router)
    app.include_router(openings_router)
    app.include_router(passwordless_auth_router)
    app.include_router(screening_router)
    app.include_router(ranking_router)
    app.include_router(settings_router)
    app.include_router(eligibility_rules_router)
    # Serve the built frontend from the API origin. API routers are registered above,
    # so they always win; this catch-all mount handles everything else — the SPA's assets and
    # its index.html (html=True serves index.html for "/" and for unknown paths). Mounted only
    # when a build exists, so tests and a build-less dev backend are unaffected (dev serves the
    # frontend from Vite on :5173). No client-side routing here, so no SPA-fallback nuance.
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="spa")
    return app


def _triggers_maintenance(request: Request) -> bool:
    path = request.url.path
    return (
        request.method != "OPTIONS"
        and path != "/health"
        and not path.startswith("/dev/previews/")
        and not path.startswith("/assets/")
        and path not in {"/favicon.ico", "/robots.txt"}
    )


app = create_app(maintenance_task=run_due_maintenance)
