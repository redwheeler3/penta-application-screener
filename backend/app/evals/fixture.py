"""Record / load an eval fixture: one Rank's model output, PII-safe and committable.

WHAT'S IN IT (all model output ABOUT the criteria, never applicant PII):
  - ``dimensions``: each settled axis's key / name / definition / high_end / low_end /
    why_it_differentiates / from_committee_request — the discovery+decompose output.
  - ``decompose`` / ``match`` / ``consolidate``: the audit trails (merge decisions,
    carry-forward map, nominated pairs) — reasoning about axes, not people.
  - ``score_vectors``: per-dimension arrays of -1..+1 scores. Candidates are keyed by an
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
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.score_vectors import load_score_vectors
from app.db.models import RankingRun, RunCostLedger
from app.evals.paths import (
    FIXTURE_PATH,
)
from app.services.ranking_run import get_current_run


@dataclass(frozen=True)
class Provenance:
    """What produced a recorded Rank — the metadata an honest eval needs to attribute a
    verdict to the exact prompt+model that generated the output under review (SPEC M13:
    "a change in the judge can be mistaken for a change in production quality").

    ``pass_models`` is EXACT: read from the run's rank ledger (`RunPassCost.model_id`), so
    it's the model each pass actually ran on. ``pass_prompt_versions`` is
    current-at-record: the pool passes are uncached, so their `PROMPT_VERSION` is not
    persisted per-run — but the recorder is invoked deliberately right after blessing a
    run, when the modules still hold the prompts that produced it, so reading them now is
    faithful. (If a prompt is edited between the run and the record, the recorder is being
    misused — record before editing, per the capture-to-fixture rule.)"""

    pass_models: dict[str, str] = field(default_factory=dict)
    pass_prompt_versions: dict[str, str] = field(default_factory=dict)


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
    provenance: Provenance = field(default_factory=Provenance)


# Pass label (the canonical RunPassCost/cost-report label) -> the AI module whose
# PROMPT_VERSION drove it. The rank-chain passes only; screening is a separate step.
# Kept beside the recorder so a new pass is added here when its label is added upstream.
_PASS_PROMPT_MODULES = {
    "Pattern discovery": "app.ai.pattern_discovery",
    "Dimension decomposition": "app.ai.dimension_decompose",
    "Dimension matching": "app.ai.dimension_matching",
    "Dimension scoring": "app.ai.dimension_scoring",
    "Dimension consolidation": "app.ai.dimension_consolidate",
}


def _build_provenance(db: Session, run: RankingRun) -> Provenance:
    """The exact models + current prompt versions behind ``run``.

    Models: the run's rank ledger, correlated by creation order — rank ledgers and
    ``RankingRun``s are created 1:1 per request, so the Nth rank ledger pairs with the Nth
    rank run (the same no-FK correlation ``metrics.py`` uses). A pass that made no call
    records "" for its model; dropped here so the map holds only passes that actually ran.
    Prompt versions: imported live from each pass module (see ``Provenance``)."""
    rank_ledgers = list(
        db.scalars(select(RunCostLedger).where(RunCostLedger.kind == "rank").order_by(RunCostLedger.id.asc()))
    )
    rank_runs = list(db.scalars(select(RankingRun).order_by(RankingRun.id.asc())))
    pass_models: dict[str, str] = {}
    try:
        nth = rank_runs.index(run)
    except ValueError:
        nth = -1
    if 0 <= nth < len(rank_ledgers):
        pass_models = {p.label: p.model_id for p in rank_ledgers[nth].passes if p.model_id}

    import importlib

    pass_prompt_versions = {
        label: importlib.import_module(module).PROMPT_VERSION
        for label, module in _PASS_PROMPT_MODULES.items()
    }
    return Provenance(pass_models=pass_models, pass_prompt_versions=pass_prompt_versions)


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
        provenance=_build_provenance(db, run),
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
        "provenance": {
            "pass_models": fixture.provenance.pass_models,
            "pass_prompt_versions": fixture.provenance.pass_prompt_versions,
        },
    }


def record(db: Session, path: Path = FIXTURE_PATH) -> EvalFixture:
    """Record the current Rank to ``path`` (pretty JSON, git-committed). Deliberate:
    re-baseline after blessing a run's output — invoked from the Evals tab
    (POST /evals/baseline), then committed to git."""
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
    prov = data.get("provenance") or {}
    return EvalFixture(
        dimensions=data["dimensions"],
        decompose=data.get("decompose"),
        match=data.get("match"),
        consolidate=data.get("consolidate"),
        score_vectors=data["score_vectors"],
        provenance=Provenance(
            pass_models=prov.get("pass_models") or {},
            pass_prompt_versions=prov.get("pass_prompt_versions") or {},
        ),
    )


# NB: no CLI entry point. Re-baselining runs from the Evals tab (POST /evals/baseline,
# which calls record(db)); `load`/`build_fixture` here are imported by the tab and tests.
