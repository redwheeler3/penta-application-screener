"""Applicant intake routes grouped by workflow."""

from fastapi import APIRouter

from app.api.applicant_application import router as application_router
from app.api.applicant_guest import router as guest_router
from app.api.applicant_links import router as links_router

router = APIRouter(prefix="/applicant", tags=["applicant intake"])
router.include_router(guest_router)
router.include_router(links_router)
router.include_router(application_router)
