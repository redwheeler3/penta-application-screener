"""The three categorical pass endpoints (consolidation / matching / decomposition) are one
shape: load golden cases → run the pass's verdict call per case → grade merge/keep (or
matches/mismatches) against the label, contested counts as passed. Their run + stability
handlers differ only in the loader, the settings model attr, the prompt-version source, the
per-case runner, and which (field-identical) response class to build. This factory captures
that one shape once; ``runs.py`` registers the three from a small spec each. Scoring and
screening are NOT here — they grade different output shapes (a band; a per-category flag set)
and carry different CaseOut fields, so they stay first-class handlers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider
from app.api.dependencies import get_ai_provider, require_current_user
from app.api.evals._shared import (
    DEFAULT_STABILITY_K,
    case_workers,
    over_cases,
    runs_out,
    select,
    stream,
)
from app.db.models import User
from app.db.session import get_db
from app.services.settings import get_app_settings


@dataclass(frozen=True)
class CategoricalPass:
    """Everything the two endpoints need that varies by pass. ``case_out``/``stability_out`` are
    the (field-identical) response-item classes; ``run_response``/``stability_response`` wrap the
    list. ``run_case``/``stability_run`` are the pass's runners; ``model_attr`` names the
    ``settings.ai.*`` model; ``prompt_version`` reads the pass's current version (called lazily so
    the import stays inside the pass module)."""

    key: str  # the eval key + route stem, e.g. "consolidation" → POST /consolidation(+ -stability)
    load_cases: Callable[[], object]
    model_attr: str
    prompt_version: Callable[[], str]
    run_case: Callable
    stability_run: Callable
    case_out: type
    run_response: type
    stability_out: type
    stability_response: type


def register(router, spec: CategoricalPass) -> None:
    """Add ``POST /{key}`` and ``POST /{key}-stability`` to ``router`` for one categorical pass."""

    @router.post(f"/{spec.key}", name=f"run_{spec.key}")
    def run(
        case: str | None = None,
        user: User = Depends(require_current_user),
        provider: AIProvider = Depends(get_ai_provider),
        db: Session = Depends(get_db),
    ) -> StreamingResponse:
        settings = get_app_settings(db)
        model = getattr(settings.ai, spec.model_attr)
        version = spec.prompt_version()
        cases = select(list(spec.load_cases()), case, lambda c: c.key)

        def one(c, case_delta):
            case_delta(f"\n\n### {c.key}\n")
            return spec.run_case(provider, c, model, on_delta=case_delta)

        def work(on_delta):
            results = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings))
            return spec.run_response(
                prompt_version=version, model=model,
                passed=sum(1 for r in results if r.case.contested or r.passed),
                total=len(results),
                cases=[
                    spec.case_out(
                        key=r.case.key, passed=r.passed, verdict=r.verdict,
                        expected=r.case.expected, contested=r.case.contested,
                        reason=r.reason, failures=r.failures,
                    )
                    for r in results
                ],
            )

        return stream(db, spec.key, version, work)

    @router.post(f"/{spec.key}-stability", name=f"run_{spec.key}_stability")
    def run_stability(
        k: int = DEFAULT_STABILITY_K,
        case: str | None = None,
        user: User = Depends(require_current_user),
        provider: AIProvider = Depends(get_ai_provider),
        db: Session = Depends(get_db),
    ) -> StreamingResponse:
        k = max(2, min(k, 10))
        settings = get_app_settings(db)
        model = getattr(settings.ai, spec.model_attr)
        version = spec.prompt_version()
        cases = select(list(spec.load_cases()), case, lambda c: c.key)

        def one(c, case_delta):
            case_delta(f"\n\n### {c.key} (x{k})\n")
            rep = spec.stability_run(provider, c, model, k=k, on_delta=case_delta)
            return spec.stability_out(
                key=c.key, marker=rep.marker, majority=rep.majority, expected=c.expected,
                contested=c.contested, agreement=rep.agreement, flipped=rep.flipped,
                tally=rep.tally, runs=runs_out(rep),
            )

        def work(on_delta):
            out = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings, fan_out=k))
            return spec.stability_response(prompt_version=version, model=model, k=k, cases=out)

        return stream(db, f"{spec.key}_stability", version, work)
