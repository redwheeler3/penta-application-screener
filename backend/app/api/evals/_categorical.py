"""Shared runner for categorical pass eval endpoints."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider
from app.api.evals._shared import (
    DEFAULT_STABILITY_K,
    ReasoningProvider,
    case_workers,
    over_cases,
    runs_out,
    select,
    stream,
)
from app.schemas.settings import effective_reasoning_effort
from app.services.settings import get_app_settings


@dataclass(frozen=True)
class CategoricalPass:
    key: str
    load_cases: Callable[[], object]
    model_attr: str
    reasoning_attr: str
    prompt_version: Callable[[], str]
    run_case: Callable
    stability_run: Callable
    case_out: type
    run_response: type
    stability_out: type
    stability_response: type


def run_categorical(
    spec: CategoricalPass,
    *,
    mode: str,
    k: int = DEFAULT_STABILITY_K,
    case: str | None,
    provider: AIProvider,
    db: Session,
) -> StreamingResponse:
    """Run one categorical pass in single-run or stability mode."""
    settings = get_app_settings(db)
    model = getattr(settings.ai, spec.model_attr)
    reasoning_effort = effective_reasoning_effort(
        model, getattr(settings.ai, spec.reasoning_attr)
    )
    configured_provider = ReasoningProvider(provider, reasoning_effort)
    version = spec.prompt_version()
    cases = select(list(spec.load_cases()), case, lambda item: item.key)

    if mode == "stability":
        k = max(2, min(k, 10))

        def one(item, case_delta):
            case_delta(f"\n\n### {item.key} (x{k})\n")
            report = spec.stability_run(
                configured_provider, item, model, k=k, on_delta=case_delta
            )
            return spec.stability_out(
                key=item.key,
                marker=report.marker,
                majority=report.majority,
                expected=item.expected,
                contested=item.contested,
                agreement=report.agreement,
                flipped=report.flipped,
                tally=report.tally,
                runs=runs_out(report),
            )

        def work(on_delta):
            output = over_cases(
                cases,
                one,
                on_delta=on_delta,
                max_workers=case_workers(settings, fan_out=k),
            )
            return spec.stability_response(
                prompt_version=version,
                model=model,
                reasoning_effort=reasoning_effort,
                k=k,
                cases=output,
            )

        return stream(db, f"{spec.key}_stability", version, work)

    def one(item, case_delta):
        case_delta(f"\n\n### {item.key}\n")
        return spec.run_case(configured_provider, item, model, on_delta=case_delta)

    def work(on_delta):
        results = over_cases(
            cases, one, on_delta=on_delta, max_workers=case_workers(settings)
        )
        return spec.run_response(
            prompt_version=version,
            model=model,
            reasoning_effort=reasoning_effort,
            passed=sum(1 for result in results if result.case.contested or result.passed),
            total=len(results),
            cases=[
                spec.case_out(
                    key=result.case.key,
                    passed=result.passed,
                    verdict=result.verdict,
                    expected=result.case.expected,
                    contested=result.case.contested,
                    reason=result.reason,
                    failures=result.failures,
                )
                for result in results
            ],
        )

    return stream(db, spec.key, version, work)
