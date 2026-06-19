"""Runs cached, cost-capped AI analysis over applications.

This is the shared engine for AI-assisted screening: it computes a cache key,
reuses a stored result when one exists, otherwise calls the provider, prices the
call, and persists the result. A spending cap is enforced against the projected
cost of the remaining (uncached) work before any new call is made.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.pricing import cost_usd, price_for_model
from app.ai.provider import AIProvider
from app.db.models import Application, ApplicationAIResult

# Bump when a prompt or schema changes so cached results from the old version
# are not reused.
PROMPT_VERSION = "8"


class SpendingCapExceeded(Exception):
    """Raised when projected cost for uncached work would exceed the cap."""

    def __init__(self, projected_usd: float, cap_usd: float) -> None:
        self.projected_usd = projected_usd
        self.cap_usd = cap_usd
        super().__init__(
            f"Projected AI cost ${projected_usd:.2f} exceeds cap ${cap_usd:.2f}."
        )


@dataclass(frozen=True)
class AnalysisOutcome:
    output: BaseModel
    cost_usd: float
    cached: bool
    # The model's reasoning narrative, if the provider surfaced one. None for
    # results stored before narratives were captured.
    narrative: str | None = None


def cache_key(*, application: Application, kind: str, model_id: str) -> str:
    """Stable key over the application content, analysis kind, model, and prompt
    version. Uses the normalized + raw content hash so an unchanged application
    re-uses its result; changing the model or prompt version misses the cache.
    """
    basis = json.dumps(
        {
            "raw_hash": application.raw_row_hash,
            "kind": kind,
            "model_id": model_id,
            "prompt_version": PROMPT_VERSION,
        },
        sort_keys=True,
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# How many recent calls to average when learning token counts from real usage.
# A window (rather than all history) keeps the average tracking recent behavior.
_USAGE_SAMPLE_SIZE = 50


def estimate_cost(
    db: Session,
    *,
    applications: list[Application],
    kind: str,
    model_id: str,
    fallback_input_tokens: int,
    fallback_output_tokens: int,
) -> dict[str, object]:
    """Estimate the cost of analyzing the given applications, excluding any that
    are already cached. Returned shape feeds the pre-run confirmation UI.

    Prefers per-call token counts learned from real usage: the current prompt
    version first, then any earlier version (still closer to reality than a
    static guess). The fallback values are used only when there is no usage
    history at all for this kind+model.
    """
    price = price_for_model(model_id)
    uncached = [
        app
        for app in applications
        if _cached_result(db, app, kind, model_id) is None
    ]
    avg_input_tokens, avg_output_tokens = _observed_avg_tokens(
        db, kind=kind, model_id=model_id
    ) or (fallback_input_tokens, fallback_output_tokens)
    per_call = (
        avg_input_tokens / 1_000_000 * price.input_per_mtok
        + avg_output_tokens / 1_000_000 * price.output_per_mtok
    )
    return {
        "total": len(applications),
        "to_analyze": len(uncached),
        "cached": len(applications) - len(uncached),
        "estimated_usd": round(per_call * len(uncached), 4),
    }


def _observed_avg_tokens(
    db: Session, *, kind: str, model_id: str
) -> tuple[int, int] | None:
    """Average input/output tokens from this kind+model's recent real calls.

    Prefers usage from the current ``PROMPT_VERSION`` (the most representative of
    what the next run will cost). If none exists yet — e.g. right after a prompt
    change, before the new version has been run — falls back to the most recent
    usage from any version, which still beats a static guess. Returns None only
    when there is no usage history at all, so the caller uses its fixed fallback.
    """
    current = _avg_tokens_query(db, kind=kind, model_id=model_id, prompt_version=PROMPT_VERSION)
    if current is not None:
        return current
    return _avg_tokens_query(db, kind=kind, model_id=model_id, prompt_version=None)


def _avg_tokens_query(
    db: Session, *, kind: str, model_id: str, prompt_version: str | None
) -> tuple[int, int] | None:
    """Average tokens over recent rows for this kind+model, optionally pinned to a
    prompt version. ``prompt_version=None`` averages across all versions.
    """
    query = (
        select(ApplicationAIResult.input_tokens, ApplicationAIResult.output_tokens)
        .where(ApplicationAIResult.kind == kind)
        .where(ApplicationAIResult.model_id == model_id)
    )
    if prompt_version is not None:
        query = query.where(ApplicationAIResult.prompt_version == prompt_version)
    rows = db.execute(
        query.order_by(ApplicationAIResult.created_at.desc()).limit(_USAGE_SAMPLE_SIZE)
    ).all()
    if not rows:
        return None
    avg_in = round(sum(r[0] for r in rows) / len(rows))
    avg_out = round(sum(r[1] for r in rows) / len(rows))
    return avg_in, avg_out


def analyze_application(
    db: Session,
    provider: AIProvider,
    *,
    application: Application,
    kind: str,
    schema: type[BaseModel],
    model_id: str,
    prompt: str,
    system_prompt: str | None = None,
) -> AnalysisOutcome:
    """Return cached analysis if present, else call the provider and store it.

    Caching is checked before any cap logic, so reusing stored results is always
    free and never blocked by a cap.
    """
    existing = _cached_result(db, application, kind, model_id)
    if existing is not None:
        return AnalysisOutcome(
            output=schema.model_validate(existing.output),
            cost_usd=existing.cost_usd,
            cached=True,
            narrative=existing.narrative,
        )

    result = provider.structured_output(
        model_id=model_id,
        schema=schema,
        prompt=prompt,
        system_prompt=system_prompt,
    )
    call_cost = cost_usd(result.model_id, result.usage)

    record = ApplicationAIResult(
        application_id=application.id,
        kind=kind,
        cache_key=cache_key(application=application, kind=kind, model_id=model_id),
        model_id=result.model_id,
        prompt_version=PROMPT_VERSION,
        output=result.output.model_dump(mode="json"),
        narrative=result.narrative,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cost_usd=call_cost,
    )
    db.add(record)
    db.commit()

    return AnalysisOutcome(
        output=result.output,
        cost_usd=call_cost,
        cached=False,
        narrative=result.narrative,
    )


def enforce_cap(estimate: dict[str, object], cap_usd: float) -> None:
    """Raise SpendingCapExceeded if the estimated cost of a run exceeds the cap.

    Call this with the result of estimate_cost() before running a batch, so a
    large uncached run is blocked at the estimate stage rather than mid-run.
    """
    projected = float(estimate["estimated_usd"])  # type: ignore[arg-type]
    if projected > cap_usd:
        raise SpendingCapExceeded(projected, cap_usd)


def _cached_result(
    db: Session, application: Application, kind: str, model_id: str
) -> ApplicationAIResult | None:
    key = cache_key(application=application, kind=kind, model_id=model_id)
    return db.scalar(
        select(ApplicationAIResult).where(ApplicationAIResult.cache_key == key)
    )
