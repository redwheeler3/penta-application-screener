"""Live consolidation eval: run golden dimension pairs through the REAL consolidation
confirm prompt+model.

Like ``live_scoring.py``, this closes the gap the judge/invariant layers can't: they grade
recorded artifacts and are blind to a prompt/model regression because the model never runs.
This freezes the INPUT (a hand-picked pair of dimension definitions, mined from real runs),
runs it through the exact production ``dimension_consolidate`` confirm prompt on the
configured consolidate model, and grades the FRESH verdict.

Grader — categorical, so deterministic exact-match (see docs/ai-evals.md "Grader
architecture"): consolidation returns merge/keep, and the case carries the human ``expected``
verdict, so the check is ``produced_verdict == expected``. No judge tier — a judge on a case
we can exact-match is redundant. (Scoring keeps a judge because it is continuous; the
categorical passes do not.) A ``contested`` case has no honest pass/fail on verdict direction,
so it is reported but not counted toward passed/total — its signal is stability, not verdict.

The pass bypasses the deterministic NOMINATE stage (correlation) — the eval hands it the pair
directly — and calls the CONFIRM prompt via ``build_prompt`` + ``structured_output``, exactly
as ``consolidate_dimensions`` does for one pair. Inputs are dimension definitions (criteria
text, not applicant PII), so no synthetic-pool guard is needed. Costs a real model call and is
non-deterministic, so it runs from the AI Quality tab, never as part of pytest/CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.ai.dimension_consolidate import SYSTEM_PROMPT, NominatedPair, build_prompt
from app.ai.provider import AIProvider
from app.ai.schemas import ConsolidationReport, JudgeReport, JudgeVerdict
from app.evals.paths import CONSOLIDATION_GOLDEN_PATH

# The two verdict strings a consolidation case can expect (the categorical label).
MERGE, KEEP = "merge", "keep"


@dataclass(frozen=True)
class ConsolidationCase:
    key: str
    # The two dimension descriptors the confirm call compares. Each is {key, name, definition}.
    pair: tuple[dict[str, object], dict[str, object]]
    expected: str  # "merge" | "keep" — the human label
    contested: bool = False
    note: str = ""
    # Optional judge question. PRESENCE IS THE SWITCH (docs/eval-case-schema.md): a non-empty
    # question ⇒ the judge also runs on this case as an independent LABEL AUDIT (its verdict
    # vs. the label); empty ⇒ no judge. The categorical pass/fail is always exact-match; the
    # judge never gates it — it only surfaces whether the label itself looks defensible.
    judge: str = ""


@dataclass(frozen=True)
class CaseResult:
    case: ConsolidationCase
    verdict: str  # "merge" | "keep" — what the real prompt produced
    reason: str
    failures: list[str] = field(default_factory=list)
    # The judge's independent verdict, when a judge ran (case carried a question); else None.
    # Informational label-audit signal — NOT part of `passed`.
    judge_verdict: str | None = None

    @property
    def passed(self) -> bool:
        # Exact-match against the label. A contested case has no honest pass/fail on
        # direction (both verdicts defensible) — the endpoint excludes it from the tally;
        # `passed` here still reports raw agreement for display.
        if self.failures:
            return False
        return self.verdict == self.case.expected


def load_cases(path: Path = CONSOLIDATION_GOLDEN_PATH) -> tuple[ConsolidationCase, ...]:
    """Load the golden consolidation cases, flattening the by-consumer blocks (metadata /
    given / judge — see docs/eval-case-schema.md) into the flat runner case."""
    data = json.loads(path.read_text())
    cases = []
    for c in data["cases"]:
        pair = c["given"]["pair"]
        meta = c["metadata"]
        cases.append(
            ConsolidationCase(
                key=c["key"],
                pair=(pair[0], pair[1]),
                expected=meta["expected"],
                contested=meta.get("contested", False),
                note=meta.get("note", ""),
                judge=(c.get("judge") or {}).get("question", ""),
            )
        )
    return tuple(cases)


def _emit(on_delta: object, text: str) -> None:
    if on_delta is not None:
        on_delta(text)  # type: ignore[operator]


def _judge_label(provider: AIProvider, case: ConsolidationCase, *, judge_model: str) -> JudgeReport:
    """Ask the independent rubric judge the case's merge/keep question from the two
    definitions alone — a LABEL AUDIT. Reuses ``judge.py`` (the same validated judge the
    Judge tab uses) via a MERGE/KEEP case. Returns the full report so the caller can both
    surface the verdict and narrate the judge's reasoning. Never gates the pass/fail — a judge
    that disagrees with ``expected`` flags the label as worth re-examining, per the reframed
    Judge-tab role (docs/ai-evals.md 'Grader architecture')."""
    from app.evals.judge import JudgeCase, judge_case

    a, b = case.pair
    jc = JudgeCase(
        key=f"live-consolidation::{case.key}",
        title=case.judge,
        task=case.judge,
        evidence={
            "key_a": a["key"], "definition_a": a["definition"],
            "key_b": b["key"], "definition_b": b["definition"],
        },
        expected=JudgeVerdict(case.expected),  # a leaning; the judge's own verdict is what we read
        pass_name="consolidation",
    )
    return judge_case(provider, jc, model_id=judge_model).report


def run_case(
    provider: AIProvider,
    case: ConsolidationCase,
    *,
    consolidate_model: str,
    judge_model: str | None = None,
    on_delta: object = None,
) -> CaseResult:
    """Run one golden pair through the REAL consolidation confirm prompt, grade the verdict
    against the label by exact match, and — when the case carries a judge question AND a
    ``judge_model`` is given — ALSO run the independent judge as a label audit.

    The exact-match verdict is the pass/fail regression gate; the judge is informational
    (surfaced, not gating). ``on_delta``, when given, receives a NARRATION of the run as
    markdown (the "thinking" the AI Quality tab shows). As in live_scoring, we emulate it from
    the real model OUTPUT — a tight structured_output call streams ~no free-form reasoning, so
    there is nothing to stream, but the produced verdict and its grounding are what a reader
    wants to watch.
    """
    a, b = case.pair
    keep_key, drop_key = str(a["key"]), str(b["key"])
    defs = {keep_key: str(a["definition"]), drop_key: str(b["definition"])}
    # One nominated pair; the eval supplies it directly (bypassing correlation nomination).
    pair = NominatedPair(keep=keep_key, drop=drop_key, r=1.0)

    _emit(on_delta, f"Consolidating **{a['name']}** ~ **{b['name']}** on `{consolidate_model}`…\n\n")
    result = provider.structured_output(
        model_id=consolidate_model,
        schema=ConsolidationReport,
        prompt=build_prompt([pair], defs),
        system_prompt=SYSTEM_PROMPT,
    )
    # The confirm returns one verdict per pair; find ours regardless of key order.
    verdict_obj = next(
        (v for v in result.output.verdicts if {v.key_a, v.key_b} == {keep_key, drop_key}),
        None,
    )
    if verdict_obj is None:
        _emit(on_delta, f"⚠️ Model returned no verdict for `{keep_key}` ~ `{drop_key}`.\n")
        return CaseResult(
            case=case, verdict="?", reason="",
            failures=["model returned no verdict for the pair"],
        )

    verdict = MERGE if verdict_obj.same_concept else KEEP
    _emit(
        on_delta,
        f"**Verdict: {verdict}** (expected {case.expected})\n\n"
        f"- _Reason:_ {verdict_obj.reason}\n\n",
    )

    failures: list[str] = []
    if case.contested:
        _emit(on_delta, "◐ Contested case — both verdicts defensible; not counted pass/fail.\n")
    elif verdict != case.expected:
        failures.append(f"verdict {verdict!r} != expected {case.expected!r}")
        _emit(on_delta, f"❌ Verdict disagrees with the label ({verdict} vs {case.expected}).\n")
    else:
        _emit(on_delta, "✓ Verdict matches the label.\n")

    # Optional label audit: run the independent judge only when the case asks for one (a judge
    # question is present) AND a judge model was supplied. The judge never gates pass/fail; a
    # disagreement with the label is a signal to re-examine the label.
    judge_verdict: str | None = None
    if case.judge and judge_model:
        _emit(on_delta, f"\nAuditing the label with the judge on `{judge_model}`…\n\n")
        report = _judge_label(provider, case, judge_model=judge_model)
        judge_verdict = report.verdict.value
        agree = "agrees with" if judge_verdict == case.expected else "DISAGREES with"
        _emit(on_delta, f"**Judge: {judge_verdict}** — {agree} the label ({case.expected}). {report.reason}\n")

    return CaseResult(
        case=case, verdict=verdict, reason=verdict_obj.reason,
        failures=failures, judge_verdict=judge_verdict,
    )
