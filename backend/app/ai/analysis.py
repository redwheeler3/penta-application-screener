"""Shared engine for cached, cost-capped AI analysis.

Computes a cache key, reuses a stored result when present, else calls the
provider, prices the call, and persists it. The spending cap is enforced against
the projected cost of the uncached work before any new call.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

# Work item / result types for run_in_pool.
T = TypeVar("T")
R = TypeVar("R")

from app.ai.pricing import cost_usd
from app.ai.provider import AIProvider, AIResult, Usage
from app.db.models import Application, ApplicationAIResult

# Length of the derived prompt-version hash (hex chars). Must fit the
# ApplicationAIResult.prompt_version column (String(20)); 12 is ample to avoid
# collisions across the handful of prompts an app ever has.
_PROMPT_VERSION_LEN = 12


def derive_prompt_version(*parts: str | None) -> str:
    """A cache version derived from a prompt's STATIC text (its instruction template
    plus system prompt), not hand-bumped.

    Each cached pass computes this once at import over its own static prompt and
    passes it into the engine, so editing that prompt — or a shared fragment it
    folds in — changes only that pass's version and re-runs only its cache. Pass the
    *static template* (placeholders for per-application or per-settings data), never
    the per-application prompt: applicant content is already covered by the
    application's ``raw_row_hash`` in the cache key, and including it would make every
    applicant a distinct "version".
    """
    basis = "\x00".join(p or "" for p in parts)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:_PROMPT_VERSION_LEN]


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
    # The model's reasoning narrative, if the provider surfaced one.
    narrative: str | None = None


def cache_key(
    *, application: Application, kind: str, model_id: str, prompt_version: str
) -> str:
    """Stable key over application content, kind, model, and prompt version. An
    unchanged application reuses its result; a new model or prompt version misses.

    ``prompt_version`` is the calling pass's ``derive_prompt_version(...)`` — passed
    in rather than read from a global so each pass's cache turns over independently
    when only its own prompt changed.
    """
    basis = json.dumps(
        {
            "raw_hash": application.raw_row_hash,
            "kind": kind,
            "model_id": model_id,
            "prompt_version": prompt_version,
        },
        sort_keys=True,
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# How many recent calls to average when learning token counts from real usage.
_USAGE_SAMPLE_SIZE = 50


def estimate_cost(
    db: Session,
    *,
    applications: list[Application],
    kind: str,
    model_id: str,
    prompt_version: str,
    fallback_input_tokens: int,
    fallback_output_tokens: int,
    usage_kind_prefix: str | None = None,
) -> dict[str, object]:
    """Estimate the cost of analyzing the applications, excluding cached ones.
    Feeds the pre-run confirmation UI.

    Prefers per-call token counts learned from real usage (current prompt version,
    then any earlier one); the fallback values apply only with no usage history.

    ``usage_kind_prefix`` lets a pass whose ``kind`` carries a per-dimension suffix
    (e.g. ``dimension_scoring:<key>``) learn from all its prior rows — token usage
    depends on prompt shape, not which dimension. Cache hits still key on the exact
    ``kind``. Defaults to exact-kind matching.
    """
    uncached = [
        app
        for app in applications
        if _cached_result(db, app, kind, model_id, prompt_version) is None
    ]
    avg_input_tokens, avg_output_tokens = observed_avg_tokens(
        db, kind=kind, model_id=model_id, prompt_version=prompt_version,
        kind_prefix=usage_kind_prefix,
    ) or (fallback_input_tokens, fallback_output_tokens)
    # Price one average call, then scale by the uncached count.
    per_call = cost_usd(
        model_id, Usage(input_tokens=avg_input_tokens, output_tokens=avg_output_tokens)
    )
    return {
        "total": len(applications),
        "to_analyze": len(uncached),
        "cached": len(applications) - len(uncached),
        "estimated_usd": round(per_call * len(uncached), 4),
    }


def observed_avg_tokens(
    db: Session, *, kind: str, model_id: str, prompt_version: str,
    kind_prefix: str | None = None,
) -> tuple[int, int] | None:
    """Average input/output tokens from this model's recent real calls.

    Matches the exact ``kind``, or every kind with ``kind_prefix`` when given (see
    ``estimate_cost``). Prefers the calling pass's current ``prompt_version``, else
    the most recent usage from any version. Returns None only with no usage history
    at all.
    """
    current = _avg_tokens_query(
        db, kind=kind, model_id=model_id, prompt_version=prompt_version, kind_prefix=kind_prefix
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
    prompt_version: str,
) -> AnalysisOutcome | None:
    """The stored outcome for this application, or None if not yet analyzed.

    Read-only half of analysis; touches the session, so the parallel path calls it
    on the main thread to decide which applications still need a model call.
    """
    existing = _cached_result(db, application, kind, model_id, prompt_version)
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
    prompt_version: str,
    result: AIResult,
) -> AnalysisOutcome:
    """Price a fresh model result, persist it, and return its outcome.

    Write half of analysis; touches the session, so the parallel path calls it on
    the main thread after a worker returns the (session-free) model result.
    """
    call_cost = cost_usd(result.model_id, result.usage)
    record = ApplicationAIResult(
        application_id=application.id,
        kind=kind,
        cache_key=cache_key(
            application=application, kind=kind, model_id=model_id,
            prompt_version=prompt_version,
        ),
        model_id=result.model_id,
        prompt_version=prompt_version,
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
    prompt_version: str,
    prompt: str,
    system_prompt: str | None = None,
) -> AnalysisOutcome:
    """Return cached analysis if present, else call the provider and store it.

    The sequential single-application path. Caching is checked before any cap, so
    reusing stored results is always free.
    """
    cached = cached_outcome(
        db, application, kind=kind, schema=schema, model_id=model_id,
        prompt_version=prompt_version,
    )
    if cached is not None:
        return cached

    result = provider.structured_output(
        model_id=model_id,
        schema=schema,
        prompt=prompt,
        system_prompt=system_prompt,
    )
    return store_result(
        db, application, kind=kind, model_id=model_id,
        prompt_version=prompt_version, result=result,
    )


@dataclass(frozen=True)
class PassResult:
    """One application's result from a screening pass, streamed as it completes."""

    application: Application
    outcome: AnalysisOutcome | None  # None when the model call failed
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.outcome is None


def run_in_pool(
    items: list[T],
    *,
    call: Callable[[T], R],
    max_workers: int,
) -> Iterator[tuple[T, R | None, Exception | None]]:
    """Run ``call(item)`` for each item across a thread pool, yielding
    ``(item, result, error)`` as each completes — ``error`` set (``result`` None)
    when that item's call raised.

    The concurrency core shared by every AI pass: bounded workers, ``as_completed``
    ordering (a slow call never blocks faster ones), per-item error isolation. Does
    NO DB/ORM work — ``call`` must be session-free, and the caller does all DB work
    on its own thread around this generator.
    """
    if not items:
        return
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        futures = {pool.submit(call, item): item for item in items}
        for future in as_completed(futures):
            item = futures[future]
            try:
                yield item, future.result(), None
            except Exception as exc:  # noqa: BLE001 — one item's failure is isolated
                yield item, None, exc


def screen_applications(
    db: Session,
    provider: AIProvider,
    *,
    applications: list[Application],
    kind: str,
    schema: type[BaseModel],
    model_id: str,
    prompt_version: str,
    build_prompt: Callable[[Application], str],
    system_prompt: str | None = None,
    max_workers: int,
    on_result: Callable[[Application, AnalysisOutcome], None] | None = None,
) -> Iterator[PassResult]:
    """Run a cached AI pass over ``applications``, yielding each result as it
    completes (cached first, then model results in completion order).

    The 1:1 engine behind screening flags and essay analysis — one application, one
    cached result, one row. Prompts are built and results stored on this thread
    (ORM access); only the model calls run in ``run_in_pool``, so the session is
    never shared. A failed call yields a ``PassResult`` with an error rather
    than aborting the batch.

    ``on_result`` is an optional side effect run per successful outcome on the
    caller's thread (e.g. screening flags applying status); informational passes omit
    it. (Dimension scoring isn't 1:1 — it has its own path on the same core.)
    """

    def finish(application: Application, outcome: AnalysisOutcome) -> PassResult:
        if on_result is not None:
            on_result(application, outcome)
        return PassResult(application=application, outcome=outcome)

    # Cache lookups and prompt building touch the ORM, so do them here. Cached
    # applications finish immediately; the rest are queued with a prebuilt prompt.
    pending: list[tuple[Application, str]] = []
    for application in applications:
        cached = cached_outcome(
            db, application, kind=kind, schema=schema, model_id=model_id,
            prompt_version=prompt_version,
        )
        if cached is not None:
            yield finish(application, cached)
        else:
            pending.append((application, build_prompt(application)))

    def call_model(item: tuple[Application, str]) -> AIResult:
        # Pure: no session, no ORM — safe to run in a worker thread.
        return provider.structured_output(
            model_id=model_id,
            schema=schema,
            prompt=item[1],
            system_prompt=system_prompt,
        )

    for (application, _prompt), result, error in run_in_pool(
        pending, call=call_model, max_workers=max_workers
    ):
        if error is not None:
            yield PassResult(application=application, outcome=None, error=str(error))
            continue
        outcome = store_result(
            db, application, kind=kind, model_id=model_id,
            prompt_version=prompt_version, result=result,
        )
        yield finish(application, outcome)


def enforce_cap(estimate: dict[str, object], cap_usd: float) -> None:
    """Raise SpendingCapExceeded if the estimate exceeds the cap. Call before a
    batch so an over-cap run is blocked at the estimate stage, not mid-run.
    """
    projected = float(estimate["estimated_usd"])  # type: ignore[arg-type]
    if projected > cap_usd:
        raise SpendingCapExceeded(projected, cap_usd)


def _cached_result(
    db: Session, application: Application, kind: str, model_id: str, prompt_version: str
) -> ApplicationAIResult | None:
    key = cache_key(
        application=application, kind=kind, model_id=model_id,
        prompt_version=prompt_version,
    )
    return db.scalar(
        select(ApplicationAIResult).where(ApplicationAIResult.cache_key == key)
    )
