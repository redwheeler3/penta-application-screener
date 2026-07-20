"""Judge-vs-human agreement metrics — the "earn trust in the judge" measurement.

Best practice (Arize, Evidently, Pragmatic Engineer, 2025/26): before trusting an
LLM-as-judge to gate/route/report, validate it against human labels with real metrics,
not an eyeballed "5/5". A judge can ace easy cases and still miss the failures you care
about — so overall agreement alone is not enough; failure-detection recall is the number
that matters (the field's "85% agreement can still be unusable" warning).

This scores ONE blind label-audit pass (one reproduce call per case — see ``judge.py``)
against the committed human labels:
  - overall agreement (share of decisive cases whose blind judge output satisfied the label)
  - Cohen's kappa (chance-corrected — raw agreement is inflated when one label dominates)
  - per-pass agreement (so a strong pass can't hide a weak one)
  - failure-detection recall/precision (over cases whose human label flags a PROBLEM — e.g.
    matching ``mismatches``, a screening defect — how many did the judge catch, and how many
    of its problem-calls were right?)

Each judged case yields a uniform outcome (agrees / human_is_problem / judge_is_problem +
compact label tokens for κ), so the SAME metrics work across all five passes, including
scoring's in-band/out-band. CONTESTED cases are excluded from every metric: their label is a
human *leaning*, not ground truth. This module does no model calls — it takes JudgeResults the
caller produced.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.evals.judge import JudgeResult


@dataclass(frozen=True)
class AgreementReport:
    n_total: int
    n_scored: int          # decisive (non-contested) cases — the denominator for agreement
    n_contested: int       # excluded from scoring, reported separately
    n_agree: int
    per_category: dict[str, tuple[int, int]]  # pass_name -> (agree, scored)
    # Failure detection over cases whose HUMAN label is a problem:
    failure_total: int     # human-labelled problems
    failure_caught: int    # ...the judge also flagged a problem (true positives)
    judge_problem_calls: int  # how many problems the judge called on scored cases (TP+FP)

    @property
    def agreement(self) -> float:
        return self.n_agree / self.n_scored if self.n_scored else 0.0

    @property
    def kappa(self) -> float | None:
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


def _cohens_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Chance-corrected agreement over (human_label, judge_label) token pairs. None if
    degenerate (fewer than 2 pairs, or only one label present so expected agreement is 1.0).
    Labels are the compact display tokens each pass emits (verdict / band / flag-set)."""
    n = len(pairs)
    if n < 2:
        return None
    observed = sum(1 for h, j in pairs if h == j) / n
    labels = {v for pair in pairs for v in pair}
    if len(labels) < 2:
        return None  # only one label in play — kappa undefined/uninformative
    h_freq = Counter(h for h, _ in pairs)
    j_freq = Counter(j for _, j in pairs)
    expected = sum((h_freq[v] / n) * (j_freq[v] / n) for v in labels)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def score_agreement(results: list[JudgeResult]) -> AgreementReport:
    """Compute judge-vs-human agreement over a set of single-pass JudgeResults.

    Excludes contested cases from all scored metrics (their label is a leaning). Each result's
    ``reproduced`` carries the uniform outcome: ``agrees`` (blind output satisfied the human
    label), ``human_is_problem``/``judge_is_problem`` (for failure detection), and the compact
    label tokens (for κ)."""
    scored = [r for r in results if not r.case.contested]
    contested = [r for r in results if r.case.contested]

    n_agree = sum(1 for r in scored if r.reproduced.agrees)

    per_category: dict[str, list[int]] = {}
    for r in scored:
        cat = per_category.setdefault(r.case.pass_name, [0, 0])
        cat[1] += 1
        if r.reproduced.agrees:
            cat[0] += 1

    # Failure detection: human-labelled problems vs. what the judge flagged as a problem.
    failure_total = sum(1 for r in scored if r.reproduced.human_is_problem)
    failure_caught = sum(
        1 for r in scored if r.reproduced.human_is_problem and r.reproduced.judge_is_problem
    )
    judge_problem_calls = sum(1 for r in scored if r.reproduced.judge_is_problem)

    # κ over the compact label tokens the judge and human carry (verdict / band / flag-set).
    pairs = [(r.reproduced.human_label, r.reproduced.judge_label) for r in scored]

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
