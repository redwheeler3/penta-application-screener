"""M20 model bake-off over the committed, synthetic per-pass golden cases.

This is an operator-run experiment, not an API route or production model switch. It runs
each selected pass's existing production prompt and deterministic grader against its current
Claude control and corresponding OpenAI challenger, then writes a PII-free JSON report.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from app.ai.dimension_consolidate import PROMPT_VERSION as CONSOLIDATION_PROMPT_VERSION
from app.ai.dimension_decompose import PROMPT_VERSION as DECOMPOSITION_PROMPT_VERSION
from app.ai.dimension_matching import PROMPT_VERSION as MATCHING_PROMPT_VERSION
from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_PROMPT_VERSION
from app.ai.model_catalog import MODEL_IDS_BY_ROUTE, model_spec
from app.ai.pricing import cost_usd
from app.ai.provider import AIProvider, AIResult, DeltaSink, SchemaT
from app.ai.screening import screening_prompt_version
from app.ai.strands_provider import StrandsProvider
from app.core.config import get_settings
from app.evals import consolidate, decompose, matching, scoring, screening

DEFAULT_OPENAI_REASONING_EFFORT = "low"


@dataclass(frozen=True)
class PassSpec:
    name: str
    control_model: str
    challenger_model: str
    load: Callable[[], tuple[Any, ...]]
    run: Callable[[AIProvider, Any, str], Any]


PASS_SPECS = {
    "screening": PassSpec(
        "screening", "haiku", "luna", screening.load_cases,
        lambda provider, case, model: screening.run_case(provider, case, screening_model=model),
    ),
    "scoring": PassSpec(
        "scoring", "haiku", "luna", scoring.load_golden,
        lambda provider, case, model: scoring.run_case(provider, case, scoring_model=model),
    ),
    "decomposition": PassSpec(
        "decomposition", "sonnet", "terra", decompose.load_cases,
        lambda provider, case, model: decompose.run_case(provider, case, decompose_model=model),
    ),
    "matching": PassSpec(
        "matching", "sonnet", "terra", matching.load_cases,
        lambda provider, case, model: matching.run_case(provider, case, match_model=model),
    ),
    "consolidation": PassSpec(
        "consolidation", "sonnet", "terra", consolidate.load_cases,
        lambda provider, case, model: consolidate.run_case(provider, case, consolidate_model=model),
    ),
}

PROMPT_VERSIONS = {
    "screening": screening_prompt_version(),
    "scoring": SCORING_PROMPT_VERSION,
    "decomposition": DECOMPOSITION_PROMPT_VERSION,
    "matching": MATCHING_PROMPT_VERSION,
    "consolidation": CONSOLIDATION_PROMPT_VERSION,
}


class MeasuringProvider:
    """Record the one model result made by a golden ``run_case`` invocation."""

    def __init__(self, delegate: AIProvider) -> None:
        self.delegate = delegate
        self.results: list[AIResult] = []

    def structured_output(
        self,
        *,
        model_id: str,
        schema: type[SchemaT],
        prompt: str,
        system_prompt: str | None = None,
        on_delta: DeltaSink | None = None,
        read_timeout: int | None = None,
    ) -> AIResult:
        result = self.delegate.structured_output(
            model_id=model_id,
            schema=schema,
            prompt=prompt,
            system_prompt=system_prompt,
            on_delta=on_delta,
            read_timeout=read_timeout,
        )
        self.results.append(result)
        return result


def run_bakeoff(
    *,
    route: str,
    region: str,
    pass_names: list[str],
    repeats: int,
    workers: int = 1,
    openai_reasoning_effort: str = DEFAULT_OPENAI_REASONING_EFFORT,
    include_control: bool = True,
    include_challenger: bool = True,
    direct_max_retries: int = 5,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run selected frozen golden cases and return a JSON-serializable report."""
    runtime = get_settings()
    provider = StrandsProvider(
        region=region,
        openai_api_key=runtime.openai_api_key,
        anthropic_api_key=runtime.anthropic_api_key,
        openai_reasoning_effort=openai_reasoning_effort,
        direct_max_retries=direct_max_retries,
    )
    models = MODEL_IDS_BY_ROUTE[route]
    wall_clock_started = time.perf_counter()
    jobs = []
    for pass_name in pass_names:
        spec = PASS_SPECS[pass_name]
        pass_models = []
        if include_control:
            pass_models.append(models[spec.control_model])
        if include_challenger:
            pass_models.append(models[spec.challenger_model])
        for model in pass_models:
            for case in spec.load():
                for repeat in range(1, repeats + 1):
                    jobs.append((spec, model, case, repeat))

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _run_one, provider, spec, model, case, repeat, openai_reasoning_effort
            ): (
                spec.name, model, case.key, repeat
            )
            for spec, model, case, repeat in jobs
        }
        for future in as_completed(futures):
            pass_name, model, case_key, repeat = futures[future]
            row = future.result()
            rows.append(row)
            error_detail = (
                f" | {row['failures'][0]}" if row["outcome"] == "error" else ""
            )
            progress(
                f"{pass_name} {model} {case_key} repeat {repeat}/{repeats}: "
                f"{'pass' if row['passed'] else 'FAIL'}{error_detail}"
            )

    rows.sort(key=lambda row: (row["pass"], row["model"], row["case"], row["repeat"]))

    return {
        "experiment": "M20 OpenAI versus Anthropic frozen golden bake-off",
        "created_at": datetime.now(UTC).isoformat(),
        "route": route,
        "region": region,
        "repeats": repeats,
        "workers": workers,
        "direct_max_retries": direct_max_retries,
        "controls_included": include_control,
        "challengers_included": include_challenger,
        "wall_clock_seconds": time.perf_counter() - wall_clock_started,
        "packages": {
            "strands-agents": version("strands-agents"),
            "openai": version("openai"),
        },
        "results": rows,
        "case_summary": _summarize_cases(rows),
        "summary": _summarize(rows),
    }


def _run_one(
    provider: AIProvider,
    spec: PassSpec,
    model: str,
    case: Any,
    repeat: int,
    openai_reasoning_effort: str,
) -> dict[str, Any]:
    measured = MeasuringProvider(provider)
    started = time.perf_counter()
    base = {
        "pass": spec.name,
        "model": model,
        "reasoning_effort": (
            openai_reasoning_effort if model_spec(model).supports_reasoning_effort else None
        ),
        "case": case.key,
        "repeat": repeat,
        "prompt_version": PROMPT_VERSIONS[spec.name],
        "contested": bool(getattr(case, "contested", False)),
    }
    try:
        result = spec.run(measured, case, model)
        contested = base["contested"]
        return base | {
            "passed": bool(result.passed) or contested,
            "outcome": _outcome(result),
            "failures": list(result.failures),
            "calls": len(measured.results),
            "input_tokens": sum(r.usage.input_tokens for r in measured.results),
            "output_tokens": sum(r.usage.output_tokens for r in measured.results),
            "cost_usd": sum(cost_usd(r.model_id, r.usage) for r in measured.results),
            "elapsed_seconds": time.perf_counter() - started,
        }
    except Exception as exc:
        return base | {
            "passed": False,
            "outcome": "error",
            "failures": [f"{type(exc).__name__}: {exc}"],
            "calls": len(measured.results),
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "elapsed_seconds": time.perf_counter() - started,
        }


def _outcome(result: Any) -> str:
    if hasattr(result, "verdict"):
        return str(result.verdict)
    if hasattr(result, "score"):
        return str(result.score)
    categories = getattr(result, "categories", None)
    if categories is not None:
        return ",".join(categories) or "no_flags"
    return "unknown"


def _summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["pass"], row["model"]), []).append(row)
    summary = []
    for (pass_name, model), group in groups.items():
        summary.append({
            "pass": pass_name,
            "model": model,
            "reasoning_effort": group[0]["reasoning_effort"],
            "passed": sum(1 for row in group if row["passed"]),
            "total": len(group),
            "errors": sum(1 for row in group if row["outcome"] == "error"),
            "input_tokens": sum(row["input_tokens"] for row in group),
            "output_tokens": sum(row["output_tokens"] for row in group),
            "cost_usd": sum(row["cost_usd"] for row in group),
            "call_seconds": sum(row["elapsed_seconds"] for row in group),
        })
    return summary


def _summarize_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["pass"], row["model"], row["case"]), []).append(row)
    summary = []
    for (pass_name, model, case), group in groups.items():
        outcomes: dict[str, int] = {}
        for row in group:
            outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
        majority_outcome, majority_count = max(outcomes.items(), key=lambda item: item[1])
        summary.append({
            "pass": pass_name,
            "model": model,
            "reasoning_effort": group[0]["reasoning_effort"],
            "case": case,
            "contested": group[0]["contested"],
            "passed": sum(1 for row in group if row["passed"]),
            "total": len(group),
            "grade_stable": len({row["passed"] for row in group}) == 1,
            "outcome_stable": len(outcomes) == 1,
            "majority_outcome": majority_outcome,
            "majority_agreement": majority_count / len(group),
            "outcomes": outcomes,
        })
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", choices=tuple(MODEL_IDS_BY_ROUTE), default="bedrock")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--direct-max-retries",
        type=int,
        choices=range(0, 11),
        default=5,
        help="Override direct-provider SDK retries; use 0 to expose the first API failure.",
    )
    parser.add_argument(
        "--openai-reasoning-effort",
        choices=("none", "low", "medium", "high", "xhigh", "max"),
        default=DEFAULT_OPENAI_REASONING_EFFORT,
    )
    parser.add_argument(
        "--passes", nargs="+", choices=tuple(PASS_SPECS), default=list(PASS_SPECS)
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--challenger-only",
        action="store_true",
        help="Run only Luna/Terra when an existing Claude control result is sufficient.",
    )
    selection.add_argument(
        "--control-only",
        action="store_true",
        help="Run only Haiku/Sonnet when an existing OpenAI result is sufficient.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    if not 1 <= args.workers <= 50:
        parser.error("--workers must be between 1 and 50")

    report = run_bakeoff(
        route=args.route,
        region=args.region,
        pass_names=args.passes,
        repeats=args.repeat,
        workers=args.workers,
        openai_reasoning_effort=args.openai_reasoning_effort,
        include_control=not args.challenger_only,
        include_challenger=not args.control_only,
        direct_max_retries=args.direct_max_retries,
        progress=lambda message: print(message, flush=True),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
