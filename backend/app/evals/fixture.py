"""Record / load an eval fixture: one Rank's model output, PII-safe and committable.

WHAT'S IN IT (all model output ABOUT the criteria, never applicant PII):
  - ``dimensions``: each settled axis's key / name / definition / high_end / low_end /
    why_it_differentiates / from_committee_request — the discovery+decompose output.
  - ``decompose`` / ``match`` / ``consolidate``: the audit trails (merge decisions,
    carry-forward map, nominated pairs) — reasoning about axes, not people.
  - ``score_vectors``: per-dimension arrays of 0..1 scores. Candidates are keyed by an
    OPAQUE INDEX (0, 1, 2, …), not their real application_id — the fixture records the
    SHAPE of how scores vary across the pool, which is what the properties check, with no
    way to tie a column back to a person.

WHAT'S NOT: no names, emails, essays, raw rows, or application_ids. The recorder maps
every real id to a stable opaque index and drops the mapping. It also STRIPS every
model narrative: free-text reasoning cites applicant specifics as examples ("care-home
choir", income splits) while discussing axes, and no eval property reads a narrative
anyway — so dropping them removes the only PII-leak surface at the source rather than
scrubbing prose. The result is safe to commit under the "no applicant data in the repo"
rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.score_vectors import load_score_vectors
from app.db.models import RankingRun
from app.services.ranking_run import get_current_run

# The committed fixture the eval tests read. One blessed Rank; re-record deliberately.
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "rank_baseline.json"


@dataclass(frozen=True)
class EvalFixture:
    """A recorded Rank's output, the substrate every property scores."""

    dimensions: list[dict]
    decompose: dict | None
    match: dict | None
    consolidate: dict | None
    # dimension key -> full-width list of scores, one slot per candidate in a shared
    # opaque column order. None marks a candidate not scored on that dimension, so
    # columns align across dimensions and a pair correlates over the slots both filled.
    score_vectors: dict[str, list[float | None]]


def build_fixture(db: Session, run: RankingRun) -> EvalFixture:
    """Assemble a PII-safe fixture from a persisted Rank.

    Score vectors are re-keyed from real application_id to an opaque, stable column
    index shared across dimensions (so a candidate is the same column in every axis, and
    correlation still means what it means), then the id mapping is discarded.
    """
    criteria = run.criteria or {}
    report = criteria.get("dimension_report") or {}

    raw_vectors = load_score_vectors(db)  # {key: {application_id: score}}
    # One shared column order across ALL dimensions: sort the union of scored ids, and
    # emit a full-width vector per dimension with None where a candidate wasn't scored.
    # Shared columns keep the vectors alignable so a pair correlates over the slots both
    # filled (as ``correlation`` intersects on shared candidates). The id->column mapping
    # is built and dropped here — no real application_id leaves this function.
    all_ids = sorted({aid for v in raw_vectors.values() for aid in v})
    score_vectors: dict[str, list[float | None]] = {
        key: [vec.get(aid) for aid in all_ids] for key, vec in raw_vectors.items()
    }

    # why_it_differentiates quotes applicant essays verbatim ("one applicant says '…'") —
    # it's the pool-grounded field by design. No property reads it, so drop it; the
    # generalized criteria text (definition/high_end/low_end) stays for the checks.
    dims = [
        {k: v for k, v in d.items() if k != "why_it_differentiates"}
        for d in report.get("dimensions", [])
    ]

    return EvalFixture(
        dimensions=dims,
        decompose=_strip_narrative(criteria.get("decompose_audit")),
        match=_strip_narrative(criteria.get("match_audit")),
        consolidate=_strip_narrative(criteria.get("consolidate_audit")),
        score_vectors=score_vectors,
    )


# Narrative keys carried by the audits — free-text reasoning that cites applicant
# specifics. Dropped from the fixture (no property reads them); see the module docstring.
_NARRATIVE_KEYS = ("narrative", "match_narrative")


def _strip_narrative(audit: dict | None) -> dict | None:
    """A copy of the audit with any free-text narrative removed (PII-leak surface)."""
    if not audit:
        return audit
    return {k: v for k, v in audit.items() if k not in _NARRATIVE_KEYS}


def _to_json(fixture: EvalFixture) -> dict:
    return {
        "dimensions": fixture.dimensions,
        "decompose": fixture.decompose,
        "match": fixture.match,
        "consolidate": fixture.consolidate,
        "score_vectors": fixture.score_vectors,
    }


def record(db: Session, path: Path = FIXTURE_PATH) -> EvalFixture:
    """Record the current Rank to ``path`` (pretty JSON, git-committed). Deliberate:
    run this to (re)baseline after blessing a run's output."""
    run = get_current_run(db)
    if run is None:
        raise RuntimeError("No ranking run to record — run a Rank first.")
    fixture = build_fixture(db, run)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_to_json(fixture), indent=2, sort_keys=True))
    return fixture


def load(path: Path = FIXTURE_PATH) -> EvalFixture:
    """Load the committed fixture for the eval tests."""
    data = json.loads(path.read_text())
    return EvalFixture(
        dimensions=data["dimensions"],
        decompose=data.get("decompose"),
        match=data.get("match"),
        consolidate=data.get("consolidate"),
        score_vectors=data["score_vectors"],
    )


def main() -> None:
    """CLI: ``uv run python -m app.evals.fixture`` records the current Rank."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        fixture = record(db)
    finally:
        db.close()
    print(
        f"Recorded {len(fixture.dimensions)} dimensions, "
        f"{len(fixture.score_vectors)} score vectors → {FIXTURE_PATH}"
    )


if __name__ == "__main__":
    main()
