"""The Judge tab: a periodic, blind LABEL AUDIT over every pass's golden cases.

The live evals are the routine regression net — each runs its pass's REAL production prompt on
the golden inputs and grades the fresh output DETERMINISTICALLY against the human label. They
answer "did production still behave?". They cannot answer "is the human label itself sound?" —
for that you need an INDEPENDENT opinion.

That is this module. For every golden case (across all five ``<pass>_golden.json`` files) it
asks a second, independent model to REPRODUCE that pass's output — from a plain-language,
editable brief (the file's ``judge_background``, "what this pass does") + the case's ``given``,
BLIND to the human label — then grades the blind output with the SAME grader the live eval
uses. Case-level agreement and explanations help the operator review the human labels.

It owns NO case files: it reads every pass's golden file. Blindness (never showing the judge
``metadata.expected``) is the load-bearing rule — a judge shown the answer rubber-stamps it.
Costs real model calls, so it runs from the Evals tab (POST /evals/judge), never in CI.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.model_catalog import MODEL_IDS_BY_ROUTE
from app.evals import stability
from app.evals.case_schema import validate_case
from app.evals.paths import GOLDEN_FILES
from app.evals.reproduce import Reproduced

DEFAULT_MODEL = MODEL_IDS_BY_ROUTE["bedrock"]["sonnet"]

# Each pass's golden file + the reproduce adapter that re-runs that pass blind (see
# app/evals/reproduce.py). Kept as lazy imports inside the dispatcher so judge.py has no
# import cycle with the live modules (they don't import judge). One entry per pass.
_PASS_FILES = GOLDEN_FILES


def _pass_module(pass_name: str):
    """One lazy adapter binding for both reproduction and request versioning."""
    from app.evals import consolidate, decompose, matching, scoring, screening
    return {"scoring": scoring, "consolidation": consolidate, "matching": matching,
            "decomposition": decompose, "screening": screening}[pass_name]


def prompt_version(dataset=None) -> str:
    """Hash captured briefs and the exact blind USER prompts/output contracts."""
    from app.evals.dataset import fingerprint, load_dataset

    captured = dataset or load_dataset()
    parts = []
    for name in _PASS_FILES:
        prompt, schema = _pass_module(name).judge_request({})
        parts.extend((captured.families[name].get("judge_background", ""), prompt,
                      schema.model_json_schema()))
    return fingerprint(parts)


@dataclass(frozen=True)
class JudgeCase:
    """One golden case seen as an audit target: which pass it exercises, the exact ``given`` the
    pass receives, the human ``expected`` label, and the pass's editable ``background`` brief.

    ``contested`` marks a case where BOTH labels are defensible from the given alone — the call
    turns on information neither production nor the judge can see. For a contested case the label
    is a human *leaning*: agreement is neither pass nor fail, disagreement is expected review
    material (never a signal to tune anything), and consistency across repeated runs is the real
    signal. ``label_rationale`` records WHY the human chose ``expected`` — surfaced in the Judge
    tab on a disagreement, as the context for deciding whether the label or the judge is wrong —
    but is HARNESS-ONLY: it is never shown to the judge (it often states the answer), preserving
    the blind-audit rule.
    """

    key: str
    pass_name: str
    given: dict
    expected: object  # str verdict (categorical) | dict band (scoring) | dict fires/absent (screening)
    background: str
    contested: bool = False
    label_rationale: str = ""


def load_cases(dataset=None) -> tuple[JudgeCase, ...]:
    """Every golden case across all five passes, as audit targets. Each file carries a
    top-level ``judge_background`` (what the pass does, editable in the UI) attached to each of
    its cases; ``metadata``/``given`` are read straight from the uniform envelope
    (docs/eval-case-schema.md). Order: the definition order of _PASS_FILES."""
    cases: list[JudgeCase] = []
    from app.evals.dataset import load_dataset
    captured = dataset or load_dataset()
    for pass_name, data in captured.families.items():
        background = data.get("judge_background", "")
        for c in data["cases"]:
            validate_case(pass_name, c)
            meta = c["metadata"]
            cases.append(
                JudgeCase(
                    key=c["key"],
                    pass_name=pass_name,
                    given=c["given"],
                    expected=meta["expected"],
                    background=background,
                    contested=meta.get("contested", False),
                    label_rationale=meta.get("label_rationale", ""),
                )
            )
    return tuple(cases)


def _reproduce(provider, case: JudgeCase, *, model_id: str) -> Reproduced:
    """Dispatch to the pass's blind reproduce adapter. Lazy imports avoid an import cycle
    (the live modules don't import judge; judge imports them here, at call time)."""
    return _pass_module(case.pass_name).judge_reproduce(
        provider, given=case.given, expected=case.expected, background=case.background, model=model_id
    )


@dataclass(frozen=True)
class JudgeResult:
    case: JudgeCase
    reproduced: Reproduced
    model_id: str

    @property
    def agrees_with_label(self) -> bool:
        return self.reproduced.agrees

    @property
    def cost_usd(self) -> float:
        return self.reproduced.cost_usd

    @property
    def marker(self) -> str:
        """How to read this result. A contested case can't pass/fail on direction (both labels
        defensible) — it's always review material, so it never shows ``[ok]``."""
        if self.case.contested:
            return "[contested]"
        return "[ok]" if self.reproduced.agrees else "[review]"


def judge_case(provider, case: JudgeCase, *, model_id: str = DEFAULT_MODEL) -> JudgeResult:
    """Reproduce one case's pass output blind and grade it against the human label."""
    return JudgeResult(case=case, reproduced=_reproduce(provider, case, model_id=model_id), model_id=model_id)


@dataclass(frozen=True)
class StabilityReport:
    """The outcome of auditing one case K times on FIXED inputs. The question is not "did the
    judge agree with the label?" (one call answers that) but "does the SAME blind audit, on the
    SAME given, return the SAME verdict every time?" A judge that flip-flops run-to-run on
    identical input is the noise that would make its label-audit unreliable; a steady one is
    trustworthy. Counting/marker delegate to the shared stability core."""

    case: JudgeCase
    # The GRADED stability token per run (e.g. "agrees" for scoring/screening, or the verdict for
    # categorical) — what the flip math (majority/agreement/flipped/marker) tallies, so incidental
    # noise inside one graded outcome doesn't read as a flip.
    labels: list[str]
    # The RAW reproduced label per run (a score, a verdict, or the actual flag set) — for DISPLAY,
    # so each run still shows what the judge concretely produced, not just "agrees". Parallel to
    # ``labels``/``details``.
    displays: list[str]
    details: list[str]  # the judge's reasoning per run (parallel to ``labels``) — explains a flip
    total_cost_usd: float

    @property
    def runs(self) -> list[stability.RunDetail]:
        """Per-run (display label, reasoning) pairs — same shape the other passes carry, so a judge
        stability flip is as self-explaining as a live-pass one. Uses the RAW display label (the
        actual score/verdict/flag set), NOT the graded token, so a screening run still shows
        'fake_contact, internal_inconsistency' rather than a bare 'agrees'."""
        return [stability.RunDetail(disp, detail) for disp, detail in zip(self.displays, self.details)]

    @property
    def majority(self) -> str:
        return stability.majority(self.labels)

    @property
    def agreement(self) -> float:
        return stability.agreement(self.labels)

    @property
    def flipped(self) -> bool:
        return stability.flipped(self.labels)


def stability_run(provider, case: JudgeCase, *, k: int = 5, model_id: str = DEFAULT_MODEL, on_delta: stability.DeltaSink = None) -> StabilityReport:
    """Audit ``case`` ``k`` times on identical input and report verdict stability. Every call
    sees the exact same brief + given, so any variation is the judge model's own run-to-run
    noise — the thing stability needs measured. The K calls run concurrently (independent
    fixed-input requests); the tally is order-free.

    ``on_delta``, if given, receives one ordered ``- run N: label — reasoning`` line per run
    AFTER the pool completes — the same live narration the other passes' stability emits (via
    the shared ``run_stability``), so the Judge tab's thinking box shows all K reasonings, not
    just the summary line."""
    from app.ai.analysis import run_in_pool

    # run_in_pool yields as-completed; sort by submitted index for stable, deterministic run
    # numbering (inputs are identical, so the order is only for legible narration).
    packed = sorted(
        run_in_pool(list(range(k)), call=lambda _i: judge_case(provider, case, model_id=model_id), max_workers=k),
        key=lambda t: t[0],
    )
    results = [r for _i, r, err in packed if not err and r is not None]
    for n, r in enumerate(results, 1):
        stability.emit(on_delta, f"- run {n}: **{r.reproduced.judge_label}** — {r.reproduced.detail}\n")
    return StabilityReport(
        case=case,
        labels=[_stability_token(case, r) for r in results],  # graded token → the flip math
        displays=[r.reproduced.judge_label for r in results],  # raw label → per-run display
        details=[r.reproduced.detail for r in results],  # keep each run's reasoning (explains a flip)
        total_cost_usd=sum(r.cost_usd for r in results),
    )


def _stability_token(case: JudgeCase, result: JudgeResult) -> str:
    """The token stability tallies for one run. Stability asks "did the GRADED outcome hold?",
    so the token must be what the case grades — not the raw produced label — for passes whose
    label isn't a single graded verdict:

    - SCORING is continuous: two different in-band scores (+0.60 vs +0.75 against [0.2, 0.75]) are
      the same outcome; token the graded agree/disagree, else in-band noise reads as a flip.
    - SCREENING grades a FLAG SET per-category (some categories fire-required, some guarded, the
      rest ungraded). Two runs that both satisfy the case but differ in an UNGRADED incidental
      flag (e.g. one adds internal_inconsistency the case neither requires nor forbids) are the
      same graded outcome; tokening the raw "fake_contact, internal_inconsistency" string would
      flip on that incidental flag. Token the graded agree/disagree.

    The three CATEGORICAL passes (consolidation/matching/decomposition) DO have a single graded
    verdict (merge/keep, matches/mismatches); keep the verdict label so a flip BETWEEN verdicts is
    the signal and the tally stays informative."""
    if case.pass_name in ("scoring", "screening"):
        return "agrees" if result.reproduced.agrees else "disagrees"
    return result.reproduced.judge_label
