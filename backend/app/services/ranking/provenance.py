"""Capture ranking inputs and configuration as audit provenance."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.input_evidence import input_fingerprint
from app.ai.model_catalog import model_identity
from app.db.models import Analysis, Application
from app.schemas.settings import AppSettings, effective_reasoning_effort
from app.services.applications.retention import current_retention_clause
from app.services.eligibility.evaluation import union_eligible_application_ids


def rank_sources_are_retained(db: Session, source_ids: list[int]) -> bool:
    retained = set(db.scalars(select(Application.id).where(
        Application.id.in_(source_ids), current_retention_clause())))
    return retained == set(source_ids)


def capture_rank_sources(db: Session, applications: list[Application]) -> tuple[list[int], bool]:
    """Freeze source identity and synthetic assurance before provider work can change the pool."""
    ids = {application.id for application in applications}
    synthetic = bool(applications) and all(application.synthetic_data for application in applications)
    for sources, verified in db.execute(select(Analysis.source_application_ids, Analysis.synthetic_data)):
        ids.update(sources or [])
        synthetic = synthetic and verified and sources is not None
    return sorted(ids), bool(synthetic)


def pool_fingerprint(
    db: Session, opening_id: int, *, applications: list[Application] | None = None
) -> str:
    """Hash the source rows in the union-eligible applicant pool."""
    if applications is None:
        eligible_ids = union_eligible_application_ids(db, opening_id)
        hashes = [input_fingerprint(raw_hash, normalized or {}, "dimension_scoring")
                  for raw_hash, normalized in db.execute(select(Application.raw_row_hash,
                      Application.normalized).where(Application.id.in_(eligible_ids)))]
    else:
        hashes = [input_fingerprint(application.raw_row_hash, application.normalized or {}, "dimension_scoring")
                  for application in applications]
    return hashlib.sha256("\n".join(sorted(hashes)).encode("utf-8")).hexdigest()[:16]


def rank_inputs_fingerprint(
    db: Session,
    opening_id: int,
    settings: AppSettings,
    *,
    applications: list[Application] | None = None,
) -> str:
    """Hash the pool, prompts, models, and active reasoning levels used by Rank."""
    captured = rank_configuration(settings)
    basis = {"pool": pool_fingerprint(db, opening_id, applications=applications),
             "passes": captured["passes"], "strategy": captured["strategy"]}
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def rank_configuration(settings: AppSettings) -> dict:
    """Capture semantic controls and route/prompt provenance before Rank starts."""
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
    return {
        "ai": settings.ai.model_dump(mode="json"),
        "strategy": {"discovery_fan_out": settings.ai.discovery_fan_out,
                     "consolidate_correlation_threshold": settings.ai.consolidate_correlation_threshold},
        "passes": {name: {"prompt_version": version, "model": model_identity(model),
                          "reasoning_effort": effective_reasoning_effort(model, effort)}
                   for name, version, model, effort in passes},
    }
