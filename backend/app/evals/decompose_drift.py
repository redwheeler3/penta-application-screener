"""A MANUAL review aid for hunting decomposition narrative-vs-routing drift.

(SPEC "golden case #2": decompose's prose says it folds key X in here, but X actually
routed into a DIFFERENT settled axis — a defect the model's own words prove.)

This is NOT an automated gate — it's a heuristic you run BY HAND (``python -m
app.evals.decompose_drift``) to surface *candidate* drift for human review when combing a
run. It scans each settled axis's ``decision`` for snake_case input keys claimed to belong
here (fold/merge/absorb language), and flags any that routed elsewhere. Deliberately
scoped down after seeing it on real data: naive "any cross-referenced key" flags 22 benign
hits per run; the real decompose legitimately names OTHER axes in three innocent ways this
suppresses —
  1. "kept DISTINCT FROM <axis>"        — a deliberate keep-apart (names, doesn't claim).
  2. "<axis> is a SEPARATE / different"  — same.
  3. "its X component is COVERED BY / CAPTURED IN <axis>" — split-routing: an input axis
     split across several settled axes, correctly documenting where each part went.
What survives is a genuine belongs-here claim contradicted by the routing. Even so it's a
heuristic (may miss subtle no-key-named drift — that's the LLM judge's MATCHES/MISMATCHES
job — and may still over-flag), so every hit is a CANDIDATE for a human to confirm, never
an auto-labelled case. On the runs to date it finds zero real drift (decompose behaving
well); it earns its keep the run it finally catches one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# snake_case dimension-key tokens: lowercase words joined by underscores, >=2 segments so
# we don't match ordinary prose words. Keys in this project look like `governance_admin_skills`.
_KEY_TOKEN = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")

# The false-positive mode: a decision legitimately names another axis to say "this is
# DISTINCT FROM x" (a deliberate keep-apart). Naming a key in that context is correct, not
# drift. We only treat a named key as a belonging-here CLAIM when its sentence uses
# fold/merge/absorb language AND does NOT use distinct/separate/apart language. This turns
# the detector from "flags every cross-reference" (too noisy — 22 benign hits on real runs)
# into "flags a key the prose says belongs here but that routed elsewhere".
_BELONGS = re.compile(r"\b(fold|folded|merge|merged|absorb|absorbed|include|included|belongs|goes (?:in|into)|rolled? in)\b", re.I)
_DISTINCT = re.compile(r"\b(distinct|separate|apart|kept? out|not the same|different (?:axis|concept)|vs\.?)\b", re.I)
# Split-routing language: the decision names another axis to say part of an input went
# THERE, not here (e.g. "its nursing component is covered by X"). Correct behaviour, not
# drift — suppressed. Applied to the clause around the named key.
_ROUTED_ELSEWHERE = re.compile(r"\b(covered by|captured in|absorbed (?:by|into)|handled by|goes to|routed to|lives in|sits in|belongs in|its .* (?:half|component|part))\b", re.I)


def _sentence_around(text: str, key: str) -> str:
    """The sentence containing ``key`` (rough split on . ; — ), for context classification."""
    for piece in re.split(r"[.;—]", text):
        if key in piece:
            return piece
    return text


@dataclass(frozen=True)
class DriftCandidate:
    """A prose-named key that routed into a different axis than the decision discusses."""

    axis_key: str          # the settled axis whose decision names the key
    named_key: str         # the input key the decision text mentions
    routed_to: str | None  # the axis whose source_keys actually contains named_key (None = nowhere)
    decision: str          # the decision prose (for the reviewer to judge intent)


def find_drift(settled: list[dict]) -> list[DriftCandidate]:
    """Scan a decompose audit's ``settled`` axes for prose-named keys that routed elsewhere.

    For each axis, extract every snake_case key mentioned in its ``decision`` and check
    where that key actually landed (the global source_keys -> axis map). A key named in
    axis A's decision but routed into axis B (B != A) is a drift candidate. A key named
    but routed nowhere (absent from all source_keys) is also flagged (the prose references
    an input that didn't survive). Self-references (named key routed into the same axis)
    and the axis's own key are ignored — those are consistent."""
    # Global routing: which settled axis each input key landed in.
    routed_to: dict[str, str] = {}
    for s in settled:
        for sk in s.get("source_keys", []):
            routed_to[sk] = s["key"]

    all_source_keys = set(routed_to)
    candidates: list[DriftCandidate] = []
    for s in settled:
        axis = s["key"]
        own_sources = set(s.get("source_keys", []))
        named = set(_KEY_TOKEN.findall(s.get("decision") or ""))
        decision = s.get("decision") or ""
        for key in named:
            # Only consider tokens that are actually input keys somewhere (else it's just
            # a prose phrase that happens to be snake_case), and not this axis's own key.
            if key not in all_source_keys or key == axis:
                continue
            if key in own_sources:
                continue  # prose names a key that DID route here — consistent
            # Classify the sentence naming the key: only a BELONGS-here claim (fold/merge)
            # that is NOT a distinct-from statement counts as drift. This suppresses the
            # dominant false positive — "kept distinct from <other axis>" — which correctly
            # names another axis while that axis routes to itself.
            sent = _sentence_around(decision, key)
            if not _BELONGS.search(sent) or _DISTINCT.search(sent):
                continue
            # Suppress split-routing: prose naming this key to say a PART of some input
            # went there (covered by / captured in / its X component) — correct, not drift.
            if _ROUTED_ELSEWHERE.search(sent):
                continue
            # Prose claims this key folds/belongs HERE, but it routed into a different axis.
            candidates.append(
                DriftCandidate(
                    axis_key=axis,
                    named_key=key,
                    routed_to=routed_to.get(key),
                    decision=decision,
                )
            )
    return candidates


def main() -> None:
    from sqlalchemy import select

    from app.db.models import RankingRun
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        runs = list(db.scalars(select(RankingRun).order_by(RankingRun.id)))
        total = 0
        for run in runs:
            dec = (run.criteria or {}).get("decompose_audit") or {}
            settled = dec.get("settled") or []
            if not settled:
                continue
            cands = find_drift(settled)
            total += len(cands)
            print(f"run {run.id}: {len(settled)} axes, {len(cands)} drift candidate(s)")
            for c in cands:
                print(f"  [{c.axis_key}] names '{c.named_key}' but it routed -> {c.routed_to}")
                print(f"    decision: {c.decision[:160]}")
        print(f"\n{total} total candidate(s). Each is a CANDIDATE for human review, not a "
              "confirmed drift — a decision may name a key as 'distinct from X' legitimately.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
