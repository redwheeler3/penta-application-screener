"""Record current criteria and scoped selected scores for an eval baseline.

The latest analysis supplies shared criteria/audits; its opening supplies the active
consumer cohort. Opaque columns align scores without exposing application IDs. Capture
uses persisted configuration and selected producer provenance, not live prompts or guessed
ledger positions. Baseline recording is local; commit/deploy the versioned file to use it
in hosted evals.

Top-level narratives and settled-dimension justifications are excluded. Nested audit prose
is retained, so this exporter does not guarantee that arbitrary real applicant data is safe
to commit. Review provenance/content before committing a fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.dimension_scoring import KIND_PREFIX
from app.ai.score_vectors import load_score_vectors
from app.db.models import Analysis, ApplicationAIResult, ApplicationAISelection
from app.evals.fixture_files import read_json, write_json
from app.evals.paths import FIXTURE_PATH
from app.services.applications.scope import opening_ai_applications
from app.services.ranking.analysis import get_latest_analysis
from app.services.ranking.audit import (
    consolidate_audit_view,
    decompose_audit_view,
    match_audit_view,
)
from app.services.ranking.dimensions import current_dimension_report


@dataclass(frozen=True)
class Provenance:
    """Captured pool-pass configuration and the selected scores' producer provenance.

    Pool models are captured semantic identities, not proof that a call ran or a billing
    receipt. Scoring uses the selected results' actual producer route and prompt. Missing
    history or multiple scoring producers/versions leave that entry unknown (absent).
    Neither live prompt modules nor unrelated ledger rows can reconstruct missing facts.
    """

    pass_models: dict[str, str] = field(default_factory=dict)
    pass_prompt_versions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalFixture:
    """Current criteria, audits and scoped scores for an eval snapshot."""

    dimensions: list[dict]
    decompose: dict | None
    match: dict | None
    consolidate: dict | None
    # dimension key -> full-width list of scores, one slot per candidate in a shared
    # opaque column order. None marks a candidate not scored on that dimension, so
    # columns align across dimensions and a pair correlates over the slots both filled.
    score_vectors: dict[str, list[float | None]]
    provenance: Provenance = field(default_factory=Provenance)


def _build_provenance(
    db: Session, analysis: Analysis, application_ids: list[int], dimension_keys: list[str],
) -> Provenance:
    """Read recorded sources; unknown history stays unknown."""
    audit = analysis.audit
    criteria_config = ((audit.fan_out or {}).get("configuration") or {}) if audit else {}
    consolidate_config = ((audit.consolidate or {}).get("configuration") or {}) if audit else {}
    pass_models: dict[str, str] = {}
    pass_prompt_versions: dict[str, str] = {}
    for label, name, config in (
        ("Pattern discovery", "discovery", criteria_config),
        ("Dimension decomposition", "decompose", criteria_config),
        ("Dimension matching", "match", criteria_config),
        ("Dimension consolidation", "consolidate", consolidate_config),
    ):
        captured = config.get("passes", {}).get(name, {})
        if captured.get("model"):
            pass_models[label] = captured["model"]
        if captured.get("prompt_version"):
            pass_prompt_versions[label] = captured["prompt_version"]

    sources = db.execute(select(ApplicationAIResult.model_id, ApplicationAIResult.prompt_version)
        .join(ApplicationAISelection, ApplicationAISelection.result_id == ApplicationAIResult.id)
        .where(ApplicationAISelection.application_id.in_(application_ids),
               ApplicationAISelection.kind.in_([f"{KIND_PREFIX}:{key}" for key in dimension_keys])))
    models, versions = set(), set()
    for model, version in sources:
        models.add(model)
        versions.add(version)
    if len(models) == 1:
        pass_models["Dimension scoring"] = models.pop()
    if len(versions) == 1:
        pass_prompt_versions["Dimension scoring"] = versions.pop()
    return Provenance(pass_models=pass_models, pass_prompt_versions=pass_prompt_versions)


def build_fixture(db: Session, analysis: Analysis) -> EvalFixture:
    """Assemble current criteria, audits and scoped selected scores for an analysis.

    Score vectors are re-keyed from real application_id to an opaque, stable column
    index shared across dimensions (so a candidate is the same column in every axis, and
    correlation still means what it means), then the id mapping is discarded.
    """
    report = current_dimension_report(analysis)
    report_dims = [d.model_dump(mode="json") for d in report.dimensions] if report else []

    application_ids = [app.id for app in opening_ai_applications(db, analysis.opening_id)] if analysis.opening_id else []
    dimension_keys = [d["key"] for d in report_dims]
    raw_vectors = load_score_vectors(db, application_ids=application_ids, dimension_keys=dimension_keys)
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
        for d in report_dims
    ]

    return EvalFixture(
        dimensions=dims,
        decompose=_strip_narrative(decompose_audit_view(analysis)),
        match=_strip_narrative(match_audit_view(analysis)),
        consolidate=_strip_narrative(consolidate_audit_view(db, analysis)),
        score_vectors=score_vectors,
        provenance=_build_provenance(db, analysis, application_ids, dimension_keys),
    )


# Free-text audit fields are excluded because they may cite applicant specifics.
_NARRATIVE_KEYS = ("narrative", "match_narrative")


def _strip_narrative(audit: dict | None) -> dict | None:
    """A copy without the top-level narrative fields."""
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
    """Record the latest analysis across openings and its scoped scores to ``path``. Deliberate:
    re-baseline after blessing a run's output — invoked from the Evals tab
    (POST /evals/baseline), then committed to git."""
    analysis = get_latest_analysis(db)
    if analysis is None:
        raise RuntimeError("No ranking run to record — run a Rank first.")
    fixture = build_fixture(db, analysis)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, _to_json(fixture), sort_keys=True)
    return fixture


def load(path: Path = FIXTURE_PATH) -> EvalFixture:
    """Load the committed fixture for the eval tests."""
    data = read_json(path)
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
