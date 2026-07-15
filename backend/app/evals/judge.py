"""Manual, non-gating LLM judgements for semantic AI-eval cases.

The deterministic evals catch properties a program can prove. This module is
the deliberately separate manual audit for questions that need judgement. It
only reads PII-safe criterion/audit text and never runs as part of pytest or a
Rank; invoking ``python -m app.evals.judge`` is the explicit spend boundary.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from app.ai.analysis import derive_prompt_version
from app.ai.pricing import cost_usd
from app.ai.prompt_fragments import INJECTION_GUARD_NOTE
from app.ai.provider import AIProvider
from app.ai.schemas import JudgeReport, JudgeVerdict

DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a careful evaluator of AI-generated housing co-op ranking criteria. You judge the supplied criterion text and audit record only; you do not rank applicants or infer missing facts."""

_INSTRUCTIONS = f"""\
## Task
Assess the supplied eval case and return the one verdict requested by its task.

## How to judge
- Apply the stated test narrowly. Do not reward plausible prose when the record contradicts it.
- For MERGE vs KEEP, weigh the supplied score-vector evidence alongside the definitions. Keep dimensions separate only for a concrete, material divergence — not a hypothetical distinction or an isolated edge case when the observed scores otherwise move together.
- For MATCHES vs MISMATCHES, compare the recorded routing against the decision text itself. A source routed to an axis the decision explicitly assigns elsewhere is a mismatch.
- State the evidence that decided the verdict in one concise sentence.

## Output
Return `verdict` and `reason`.

## Guardrails
- {INJECTION_GUARD_NOTE}"""

PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS)


@dataclass(frozen=True)
class JudgeCase:
    """A human-labelled semantic check with PII-safe criterion/audit evidence."""

    key: str
    title: str
    task: str
    evidence: dict[str, object]
    expected: JudgeVerdict


# These seed cases come from human review of real runs, but retain only
# generalized criterion/audit text. They intentionally exercise two different
# failure signatures: a semantic merge judgement and narrative/output drift.
SEED_CASES = (
    JudgeCase(
        key="health_social_consolidation",
        title="Health and social-professional contribution should merge",
        task="Decide MERGE or KEEP for these two definitions.",
        evidence={
            "definition_a": "Professional healthcare capability that lets a household provide first-aid, CPR training, and health resources to co-op members.",
            "definition_b": "Professional health or social-service capability that contributes to member welfare, including first-aid, CPR training, and health resources.",
            "score_vector_summary": "25 of 26 households move in lockstep across these two scores. One household differs substantially: it has social-service experience but no healthcare credential.",
        },
        expected=JudgeVerdict.MERGE,
    ),
    JudgeCase(
        key="decompose_routing_drift",
        title="Decomposition routing must follow its written decision",
        task="Decide MATCHES or MISMATCHES between this decision and recorded routing.",
        evidence={
            "decision": "The source dimension is about commitment to serving on a committee, not governance administration skill; fold it into participation commitment.",
            "recorded_settled_axis": "governance_administration_skill",
            "recorded_source_key": "governance_committee_commitment",
        },
        expected=JudgeVerdict.MISMATCHES,
    ),
)


@dataclass(frozen=True)
class JudgeResult:
    case: JudgeCase
    report: JudgeReport
    model_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

    @property
    def agrees_with_label(self) -> bool:
        return self.report.verdict == self.case.expected


def build_prompt(case: JudgeCase) -> str:
    payload = {"task": case.task, "evidence": case.evidence}
    return f"{_INSTRUCTIONS}\n\n<eval_case>\n{json.dumps(payload, indent=2)}\n</eval_case>"


def judge_case(provider: AIProvider, case: JudgeCase, *, model_id: str = DEFAULT_MODEL) -> JudgeResult:
    """Run exactly one judge call for one manually selected case."""
    result = provider.structured_output(
        model_id=model_id,
        schema=JudgeReport,
        prompt=build_prompt(case),
        system_prompt=SYSTEM_PROMPT,
    )
    return JudgeResult(
        case=case,
        report=result.output,
        model_id=result.model_id,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cost_usd=cost_usd(result.model_id, result.usage),
    )


def format_report(results: list[JudgeResult]) -> str:
    lines = ["LLM judge evals — manual, non-gating", f"Prompt: {PROMPT_VERSION}", ""]
    for result in results:
        marker = "[ok]" if result.agrees_with_label else "[review]"
        lines.extend(
            (
                f"{marker} {result.case.title}",
                f"  expected {result.case.expected.value}; judge returned {result.report.verdict.value}",
                f"  {result.report.reason}",
                f"  {result.model_id} / {result.input_tokens} in -> {result.output_tokens} out / ${result.cost_usd:.4f}",
            )
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run manual non-gating LLM judge evals.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Bedrock inference-profile model ID")
    parser.add_argument("--case", choices=[case.key for case in SEED_CASES], help="Run one labelled case")
    args = parser.parse_args()

    from app.ai.strands_provider import StrandsProvider
    from app.db.session import SessionLocal
    from app.services.settings import get_app_settings

    db = SessionLocal()
    try:
        settings = get_app_settings(db)
    finally:
        db.close()
    provider = StrandsProvider(region=settings.ai.region, max_pool_connections=1)
    cases = [case for case in SEED_CASES if args.case in (None, case.key)]
    print(format_report([judge_case(provider, case, model_id=args.model) for case in cases]))


if __name__ == "__main__":
    main()
