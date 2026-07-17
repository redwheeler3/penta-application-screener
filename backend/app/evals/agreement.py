"""Judge-vs-human agreement metrics — the "earn trust in the judge" measurement.

Best practice (Arize, Evidently, Pragmatic Engineer, 2025/26): before trusting an
LLM-as-judge to gate/route/report, validate it against human labels with real metrics,
not an eyeballed "5/5". A judge can ace easy cases and still miss the failures you care
about — so overall agreement alone is not enough; failure-detection recall is the number
that matters (the field's "85% agreement can still be unusable" warning).

This scores ONE judge pass (one call per case) against the committed human labels:
  - overall agreement (share of decisive cases the judge matched)
  - Cohen's kappa (chance-corrected — raw agreement is inflated when one label dominates)
  - per-category agreement (so a strong "supported" score can't hide weak "unsupported")
  - failure-detection recall/precision (of the cases whose human label flags a PROBLEM —
    unsupported / mismatches / flag_unsupported — how many did the judge catch, and how
    many of its problem-calls were right?)

CONTESTED cases are excluded from every metric: their label is a human *leaning*, not
ground truth, so scoring the judge against it would penalise a defensible call (the field:
don't force binary on genuinely indeterminate cases). They're counted and reported
separately. This module does no model calls — it takes JudgeResults the caller produced.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.ai.schemas import JudgeVerdict
from app.evals.judge import JudgeResult

# The verdict in each two-way family that means "a problem was caught" — the failure the
# eval exists to detect. Agreement on these is what "does the judge catch what matters"
# measures; the other side (merge/supported/matches/flag_supported) is the clean case.
_PROBLEM_VERDICTS: frozenset[JudgeVerdict] = frozenset({
    JudgeVerdict.UNSUPPORTED,       # scoring: score not supported by evidence
    JudgeVerdict.MISMATCHES,        # matching: a wrong match
    JudgeVerdict.FLAG_UNSUPPORTED,  # screening: an over-reaching flag
    # merge/keep has no single "problem" side (either can be the defect depending on the
    # pair), so consolidation/decompose cases contribute to overall agreement + kappa but
    # NOT to the failure-recall metric — noted in the report so it isn't a silent omission.
})


@dataclass(frozen=True)
class AgreementReport:
    n_total: int
    n_scored: int          # decisive (non-contested) cases — the denominator for agreement
    n_contested: int       # excluded from scoring, reported separately
    n_agree: int
    per_category: dict[str, tuple[int, int]]  # pass_name -> (agree, scored)
    # Failure detection over cases whose HUMAN label is a problem verdict:
    failure_total: int     # human-labelled problems
    failure_caught: int    # ...the judge also called a problem (true positives)
    judge_problem_calls: int  # how many problems the judge called on scored cases (TP+FP)

    @property
    def agreement(self) -> float:
        return self.n_agree / self.n_scored if self.n_scored else 0.0

    @property
    def kappa(self) -> float | None:
        """Cohen's kappa over the two-way agree/disagree isn't meaningful; instead compute
        it over the verdict labels. Returns None when undefined (single class)."""
        return self._kappa

    _kappa: float | None = None

    @property
    def failure_recall(self) -> float | None:
        """Of human-labelled problems, the share the judge also flagged. None if no
        problem-labelled cases in the set."""
        return self.failure_caught / self.failure_total if self.failure_total else None

    @property
    def failure_precision(self) -> float | None:
        """Of the judge's problem-calls, the share that were real. None if it called none."""
        return self.failure_caught / self.judge_problem_calls if self.judge_problem_calls else None


def _cohens_kappa(pairs: list[tuple[JudgeVerdict, JudgeVerdict]]) -> float | None:
    """Chance-corrected agreement over (human, judge) verdict pairs. None if degenerate
    (fewer than 2 pairs, or only one label present so expected agreement is 1.0)."""
    n = len(pairs)
    if n < 2:
        return None
    observed = sum(1 for h, j in pairs if h == j) / n
    labels = {v for pair in pairs for v in pair}
    if len(labels) < 2:
        return None  # only one verdict in play — kappa undefined/uninformative
    h_freq = Counter(h for h, _ in pairs)
    j_freq = Counter(j for _, j in pairs)
    expected = sum((h_freq[v] / n) * (j_freq[v] / n) for v in labels)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def score_agreement(results: list[JudgeResult]) -> AgreementReport:
    """Compute judge-vs-human agreement over a set of single-pass JudgeResults.

    Excludes contested cases from all scored metrics (their label is a leaning). Uses each
    case's ``expected`` as the human label and the judge's returned verdict as the call."""
    scored = [r for r in results if not r.case.contested]
    contested = [r for r in results if r.case.contested]

    pairs = [(r.case.expected, r.report.verdict) for r in scored]
    n_agree = sum(1 for h, j in pairs if h == j)

    per_category: dict[str, list[int]] = {}
    for r in scored:
        cat = per_category.setdefault(r.case.pass_name, [0, 0])
        cat[1] += 1
        if r.case.expected == r.report.verdict:
            cat[0] += 1

    # Failure detection: human-labelled problems vs. what the judge flagged as a problem.
    failure_total = sum(1 for r in scored if r.case.expected in _PROBLEM_VERDICTS)
    failure_caught = sum(
        1 for r in scored
        if r.case.expected in _PROBLEM_VERDICTS and r.report.verdict in _PROBLEM_VERDICTS
    )
    judge_problem_calls = sum(1 for r in scored if r.report.verdict in _PROBLEM_VERDICTS)

    report = AgreementReport(
        n_total=len(results),
        n_scored=len(scored),
        n_contested=len(contested),
        n_agree=n_agree,
        per_category={k: (v[0], v[1]) for k, v in per_category.items()},
        failure_total=failure_total,
        failure_caught=failure_caught,
        judge_problem_calls=judge_problem_calls,
    )
    object.__setattr__(report, "_kappa", _cohens_kappa(pairs))
    return report


def format_agreement(report: AgreementReport) -> str:
    lines = [
        "Judge vs. human agreement (single pass; contested excluded)",
        f"  overall: {report.n_agree}/{report.n_scored} = {report.agreement:.0%}"
        + (f"   kappa={report.kappa:.2f}" if report.kappa is not None else "   kappa=n/a"),
        f"  contested (excluded, reported separately): {report.n_contested}",
        "  per AI step (agree/scored):",
    ]
    for cat in sorted(report.per_category):
        agree, scored = report.per_category[cat]
        lines.append(f"    {cat:15s} {agree}/{scored} = {agree / scored:.0%}")
    if report.failure_total:
        rec = report.failure_recall
        prec = report.failure_precision
        lines.append(
            f"  failure detection (the number that matters): "
            f"recall {report.failure_caught}/{report.failure_total} = {rec:.0%}"
            + (f", precision {prec:.0%}" if prec is not None else "")
        )
    else:
        lines.append("  failure detection: no problem-labelled cases in this set")
    return "\n".join(lines)
