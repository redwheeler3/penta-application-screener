"""Runs cached, cost-capped AI analysis over applications.

This is the shared engine for AI-assisted screening: it computes a cache key,
reuses a stored result when one exists, otherwise calls the provider, prices the
call, and persists the result. A spending cap is enforced against the projected
cost of the remaining (uncached) work before any new call is made.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.pricing import cost_usd
from app.ai.provider import AIProvider, AIResult, Usage
from app.db.models import Application, ApplicationAIResult

# Bump when a prompt or schema changes so cached results from the old version
# are not reused.
PROMPT_VERSION = "9"


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
    usage_kind_prefix: str | None = None,
) -> dict[str, object]:
    """Estimate the cost of analyzing the given applications, excluding any that
    are already cached. Returned shape feeds the pre-run confirmation UI.

    Prefers per-call token counts learned from real usage: the current prompt
    version first, then any earlier version (still closer to reality than a
    static guess). The fallback values are used only when there is no usage
    history at all.

    ``usage_kind_prefix`` lets a pass whose ``kind`` carries a per-run suffix
    (e.g. ``dimension_scoring:<dims_hash>``) learn from *all* its prior runs:
    token usage depends on the prompt shape, not on which dimensions were
    discovered, so averaging across every ``dimension_scoring:*`` row keeps the
    estimate self-tuning even though each run gets a fresh hash. Cache hits still
    key on the exact ``kind``. Defaults to exact-kind matching.
    """
    uncached = [
        app
        for app in applications
        if _cached_result(db, app, kind, model_id) is None
    ]
    avg_input_tokens, avg_output_tokens = _observed_avg_tokens(
        db, kind=kind, model_id=model_id, kind_prefix=usage_kind_prefix
    ) or (fallback_input_tokens, fallback_output_tokens)
    # Price one average call through the same formula as a real call, then scale
    # by how many uncached applications will actually be sent.
    per_call = cost_usd(
        model_id, Usage(input_tokens=avg_input_tokens, output_tokens=avg_output_tokens)
    )
    return {
        "total": len(applications),
        "to_analyze": len(uncached),
        "cached": len(applications) - len(uncached),
        "estimated_usd": round(per_call * len(uncached), 4),
    }


def _observed_avg_tokens(
    db: Session, *, kind: str, model_id: str, kind_prefix: str | None = None
) -> tuple[int, int] | None:
    """Average input/output tokens from this model's recent real calls for the
    pass.

    Matches on the exact ``kind`` unless ``kind_prefix`` is given, in which case
    it matches every kind starting with that prefix (see ``estimate_cost`` for
    why scoring needs this). Prefers usage from the current ``PROMPT_VERSION``
    (the most representative of what the next run will cost). If none exists yet —
    e.g. right after a prompt change — falls back to the most recent usage from
    any version, which still beats a static guess. Returns None only when there
    is no usage history at all, so the caller uses its fixed fallback.
    """
    current = _avg_tokens_query(
        db, kind=kind, model_id=model_id, prompt_version=PROMPT_VERSION, kind_prefix=kind_prefix
    )
    if current is not None:
        return current
    return _avg_tokens_query(
        db, kind=kind, model_id=model_id, prompt_version=None, kind_prefix=kind_prefix
    )


def _avg_tokens_query(
    db: Session, *, kind: str, model_id: str, prompt_version: str | None,
    kind_prefix: str | None = None,
) -> tuple[int, int] | None:
    """Average tokens over recent rows for this model, matching the exact ``kind``
    or — when ``kind_prefix`` is set — every kind starting with that prefix.
    ``prompt_version=None`` averages across all versions.
    """
    query = select(ApplicationAIResult.input_tokens, ApplicationAIResult.output_tokens)
    if kind_prefix is not None:
        query = query.where(ApplicationAIResult.kind.like(f"{kind_prefix}%"))
    else:
        query = query.where(ApplicationAIResult.kind == kind)
    query = query.where(ApplicationAIResult.model_id == model_id)
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


def cached_outcome(
    db: Session,
    application: Application,
    *,
    kind: str,
    schema: type[BaseModel],
    model_id: str,
) -> AnalysisOutcome | None:
    """The stored outcome for this application, or None if not yet analyzed.

    This is the read-only half of analysis and the only DB access on the hot
    path that must happen before a model call. The parallel screening path calls
    it on the main thread (it touches the session) to decide which applications
    still need a model call.
    """
    existing = _cached_result(db, application, kind, model_id)
    if existing is None:
        return None
    return AnalysisOutcome(
        output=schema.model_validate(existing.output),
        cost_usd=existing.cost_usd,
        cached=True,
        narrative=existing.narrative,
    )


def store_result(
    db: Session,
    application: Application,
    *,
    kind: str,
    model_id: str,
    result: AIResult,
) -> AnalysisOutcome:
    """Price a fresh model result, persist it, and return its outcome.

    The write half of analysis. Like ``cached_outcome`` it touches the session,
    so the parallel path calls it on the main thread after a worker returns the
    (session-free) model result.
    """
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

    The sequential single-application path, composed from the same building
    blocks the parallel screening path uses. Caching is checked before any cap
    logic, so reusing stored results is always free and never blocked by a cap.
    """
    cached = cached_outcome(db, application, kind=kind, schema=schema, model_id=model_id)
    if cached is not None:
        return cached

    result = provider.structured_output(
        model_id=model_id,
        schema=schema,
        prompt=prompt,
        system_prompt=system_prompt,
    )
    return store_result(db, application, kind=kind, model_id=model_id, result=result)


@dataclass(frozen=True)
class ScreeningResult:
    """One application's result from a screening pass, streamed as it completes."""

    application: Application
    outcome: AnalysisOutcome | None  # None when the model call failed
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.outcome is None


def screen_applications(
    db: Session,
    provider: AIProvider,
    *,
    applications: list[Application],
    kind: str,
    schema: type[BaseModel],
    model_id: str,
    build_prompt: Callable[[Application], str],
    system_prompt: str | None = None,
    max_workers: int,
    on_result: Callable[[Application, AnalysisOutcome], None] | None = None,
) -> Iterator[ScreeningResult]:
    """Run a cached AI pass over ``applications``, yielding each result as it
    completes (cached results first, then model results in completion order).

    The shared engine behind every screening pass (quality flags, essay
    analysis, …). Only the blocking model call runs in worker threads; every DB
    and ORM access — cache lookup, prompt building, persistence, and the
    ``on_result`` hook — stays on this (the caller's) thread, so the session is
    never shared. Workers receive a plain prompt string and return a
    session-free result. A failed call yields a ``ScreeningResult`` with an
    error rather than aborting the batch.

    ``on_result`` is an optional side effect run on the caller's thread for each
    successful outcome (e.g. quality flags applying status). Passes that are
    purely informational, like essay analysis, omit it.
    """

    def finish(application: Application, outcome: AnalysisOutcome) -> ScreeningResult:
        if on_result is not None:
            on_result(application, outcome)
        return ScreeningResult(application=application, outcome=outcome)

    # Cache lookups and prompt building touch the ORM, so do them here, up front.
    # Cached applications are finished immediately; the rest are queued for the
    # pool with a prebuilt prompt.
    pending: list[tuple[Application, str]] = []
    for application in applications:
        cached = cached_outcome(
            db, application, kind=kind, schema=schema, model_id=model_id
        )
        if cached is not None:
            yield finish(application, cached)
        else:
            pending.append((application, build_prompt(application)))

    if not pending:
        return

    def call_model(prompt: str) -> AIResult:
        # Pure: no session, no ORM — safe to run in a worker thread.
        return provider.structured_output(
            model_id=model_id,
            schema=schema,
            prompt=prompt,
            system_prompt=system_prompt,
        )

    with ThreadPoolExecutor(max_workers=min(max_workers, len(pending))) as pool:
        futures = {
            pool.submit(call_model, prompt): application
            for application, prompt in pending
        }
        # as_completed (not map) so a slow call never holds back faster ones.
        for future in as_completed(futures):
            application = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 — one app's failure is isolated
                yield ScreeningResult(
                    application=application, outcome=None, error=str(exc)
                )
                continue
            outcome = store_result(
                db, application, kind=kind, model_id=model_id, result=result
            )
            yield finish(application, outcome)


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
