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
from pathlib import Path

from app.ai.analysis import derive_prompt_version
from app.ai.pricing import cost_usd
from app.ai.prompt_fragments import INJECTION_GUARD_NOTE
from app.ai.provider import AIProvider
from app.ai.schemas import JudgeReport, JudgeVerdict

DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"

# The committed set of human-labelled judge cases. Each is an EXACT slice of a real Rank
# (PII-safe criterion/audit text) plus its label, the rationale for that label, and the
# provenance (models + prompt versions) of the run it came from — so a verdict is always
# attributable to the exact prompt+model that produced the output under review. Grow it by
# hand when a run surfaces a judge-worthy decision: copy the exact criterion/audit text
# and the run's provenance out of a recorded fixture into a new entry with a human label +
# rationale. Never hand-fabricate an "exact" case — a lost run stays lost.
CASES_PATH = Path(__file__).parent / "fixtures" / "judge_cases.json"

SYSTEM_PROMPT = """You are a careful evaluator of AI-generated housing co-op ranking criteria. You judge the supplied criterion text and audit record only; you do not rank applicants or infer missing facts."""

_INSTRUCTIONS = f"""\
## Task
Assess the supplied eval case and return the one verdict requested by its task.

## How to judge
- Apply the stated test narrowly. Do not reward plausible prose when the record contradicts it.
- For MERGE vs KEEP, the two dimensions were flagged BECAUSE their per-applicant scores already move together closely — that near-identical scoring is a given, not something you need re-shown. Judge the two DEFINITIONS: would they score the same applicant the same way, for the same reason? KEEP apart only when you can name a concrete, plausible applicant who lands genuinely HIGH on one and LOW on the other for a real reason; a faint or hypothetical difference, or an isolated edge case against an otherwise shared core, is not enough — when it is close, they are one axis.
- For MATCHES vs MISMATCHES, compare the recorded routing against the decision text itself. A source routed to an axis the decision explicitly assigns elsewhere is a mismatch.
- State the evidence that decided the verdict in one concise sentence.

## Output
Return `verdict` and `reason`.

## Guardrails
- {INJECTION_GUARD_NOTE}"""

PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS)


@dataclass(frozen=True)
class JudgeCase:
    """A human-labelled semantic check with PII-safe criterion/audit evidence.

    ``label_rationale`` records WHY the human assigned ``expected`` — so a future reader
    (or a judge disagreement) can weigh the label instead of trusting a bare verdict.
    ``provenance`` is the models + prompt versions of the run this evidence came from
    (empty for a case whose source run wasn't retained). ``source`` names the origin run/
    fixture for traceability."""

    key: str
    title: str
    task: str
    evidence: dict[str, object]
    expected: JudgeVerdict
    label_rationale: str = ""
    provenance: dict[str, object] = None  # type: ignore[assignment]
    source: str = ""

    def __post_init__(self) -> None:
        if self.provenance is None:
            object.__setattr__(self, "provenance", {})


def load_cases(path: Path = CASES_PATH) -> tuple[JudgeCase, ...]:
    """The committed human-labelled cases. Exact slices of real Ranks; see ``CASES_PATH``."""
    data = json.loads(path.read_text())
    return tuple(
        JudgeCase(
            key=c["key"],
            title=c["title"],
            task=c["task"],
            evidence=c["evidence"],
            expected=JudgeVerdict(c["expected"]),
            label_rationale=c.get("label_rationale", ""),
            provenance=c.get("provenance") or {},
            source=c.get("source", ""),
        )
        for c in data["cases"]
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
    all_cases = load_cases()
    parser = argparse.ArgumentParser(description="Run manual non-gating LLM judge evals.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Bedrock inference-profile model ID")
    parser.add_argument("--case", choices=[case.key for case in all_cases], help="Run one labelled case")
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
    cases = [case for case in all_cases if args.case in (None, case.key)]
    print(format_report([judge_case(provider, case, model_id=args.model) for case in cases]))


if __name__ == "__main__":
    main()
