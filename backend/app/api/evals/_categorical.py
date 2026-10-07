"""Shared runner for categorical pass eval endpoints."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.pass_catalog import ai_pass
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
from app.evals.dataset import load_dataset
from app.schemas.settings import effective_reasoning_effort
from app.services.settings import get_app_settings


@dataclass(frozen=True)
class CategoricalPass:
    key: str
    load_cases: Callable
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
    binding = ai_pass(spec.key)
    if binding is None:
        raise ValueError(f"No configurable AI pass for {spec.key!r}")
    model = getattr(settings.ai, binding.model_attr)
    reasoning_effort = effective_reasoning_effort(
        model, getattr(settings.ai, binding.reasoning_attr)
    )
    configured_provider = ReasoningProvider(provider, reasoning_effort)
    version = spec.prompt_version()
    dataset = load_dataset(spec.key)
    fingerprints = dataset.case_fingerprints(spec.key)
    cases = select(list(spec.load_cases(data=dataset.families[spec.key])), case, lambda item: item.key)

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

        return stream(db, f"{spec.key}_stability", version, work, case_fingerprints=fingerprints)

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
            passed=sum(1 for result in results if not result.error and (result.case.contested or result.passed)),
            total=len(results),
            cases=[
                spec.case_out(
                    key=result.case.key,
                    passed=result.passed,
                    verdict=result.verdict,
                    expected=result.case.expected,
                    contested=result.case.contested,
                    reason=result.reason,
                    failures=result.failures, error=result.error,
                )
                for result in results
            ],
        )

    return stream(db, spec.key, version, work, case_fingerprints=fingerprints)
