"""Fingerprint the inputs that determine whether a shared ranking is current."""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.model_catalog import model_identity
from app.db.models import Application
from app.schemas.settings import AppSettings, effective_reasoning_effort
from app.services.eligibility import union_eligible_application_ids


def pool_fingerprint(
    db: Session, *, applications: list[Application] | None = None
) -> str:
    """Hash the source rows in the union-eligible applicant pool."""
    if applications is None:
        eligible_ids = union_eligible_application_ids(db)
        hashes = db.scalars(
            select(Application.raw_row_hash).where(Application.id.in_(eligible_ids))
        ).all()
    else:
        hashes = [application.raw_row_hash for application in applications]
    return hashlib.sha256("\n".join(sorted(hashes)).encode("utf-8")).hexdigest()[:16]


def rank_inputs_fingerprint(
    db: Session,
    settings: AppSettings,
    *,
    applications: list[Application] | None = None,
) -> str:
    """Hash the pool, prompts, models, and active reasoning levels used by Rank."""
    from app.ai.dimension_consolidation import PROMPT_VERSION as CONSOLIDATE_VERSION
    from app.ai.dimension_decomposition import PROMPT_VERSION as DECOMPOSE_VERSION
    from app.ai.dimension_discovery import PROMPT_VERSION as DISCOVERY_VERSION
    from app.ai.dimension_matching import PROMPT_VERSION as MATCH_VERSION
    from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_VERSION

    passes = (
        ("discovery", DISCOVERY_VERSION, settings.ai.discovery_model, settings.ai.discovery_reasoning_effort),
        ("decompose", DECOMPOSE_VERSION, settings.ai.decompose_model, settings.ai.decompose_reasoning_effort),
        ("match", MATCH_VERSION, settings.ai.match_model, settings.ai.match_reasoning_effort),
        (
            "scoring",
            SCORING_VERSION,
            settings.ai.dimension_scoring_model,
            settings.ai.dimension_scoring_reasoning_effort,
        ),
        (
            "consolidate",
            CONSOLIDATE_VERSION,
            settings.ai.consolidate_model,
            settings.ai.consolidate_reasoning_effort,
        ),
    )
    parts = [pool_fingerprint(db, applications=applications)]
    for pass_name, prompt_version, model_id, configured_effort in passes:
        parts.extend((f"{pass_name}:{prompt_version}", f"{pass_name}_model:{model_identity(model_id)}"))
        effort = effective_reasoning_effort(model_id, configured_effort)
        if effort is not None:
            parts.append(f"{pass_name}_reasoning:{effort}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
