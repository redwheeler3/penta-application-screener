"""capture_scores proposes score-defensibility cases — but only for a synthetic pool.

The safety-critical assertion: propose_cases goes through the synthetic guard, so a run
whose source sheet isn't allowlisted yields NO cases (raises), never a leak of real
applicant evidence. On a synthetic run it emits well-shaped, opaque-indexed, UNLABELLED
candidates carrying the dimension definition + cited evidence + score."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import ApplicationAIResult, RankingRun, SyncRun
from app.evals.capture_scores import propose_cases
from app.evals.synthetic_guard import SYNTHETIC_SHEET_IDS, NonSyntheticPoolError

_SYNTHETIC = next(iter(SYNTHETIC_SHEET_IDS))

_REPORT = {
    "dimension_report": {
        "dimensions": [{
            "key": "trade_depth", "name": "Trade depth",
            "definition": "Depth of demonstrated building-system trade skill.",
            "high_end": "licensed, specific systems", "low_end": "no trade skill",
            "why_it_differentiates": "varies", "from_committee_request": False,
        }],
    },
}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db: Session, sheet_id: str) -> RankingRun:
    sync = SyncRun(source_sheet_id=sheet_id, row_count=1, settings_fingerprint="fp")
    db.add(sync)
    db.flush()
    run = RankingRun(name="r", criteria=_REPORT, status="patterns_discovered",
                     source_sync_run_id=sync.id)
    db.add(run)
    # two scored rows on the same dimension, different applicants
    db.add_all([
        ApplicationAIResult(
            application_id=42, kind="dimension_scoring:trade_depth",
            cache_key="ck1", model_id="m", prompt_version="v",
            output={"dimension_key": "trade_depth", "score": 0.9,
                    "rationale": "r", "evidence": "\"I'm a licensed electrician.\"", "confidence": "high"},
        ),
        ApplicationAIResult(
            application_id=7, kind="dimension_scoring:trade_depth",
            cache_key="ck2", model_id="m", prompt_version="v",
            output={"dimension_key": "trade_depth", "score": 0.9,
                    "rationale": "r", "evidence": "\"I'm pretty handy.\"", "confidence": "low"},
        ),
    ])
    db.flush()
    return run


def test_non_synthetic_run_is_refused(db) -> None:
    run = _seed(db, "some-real-deployment-sheet")
    with pytest.raises(NonSyntheticPoolError):
        propose_cases(db, run)


def test_synthetic_run_yields_shaped_unlabelled_candidates(db) -> None:
    run = _seed(db, _SYNTHETIC)

    cases = propose_cases(db, run)

    assert len(cases) == 2
    c = cases[0]
    # Grouped by consumer: evidence + prompt are what the judge sees; metadata is harness-only.
    assert c["metadata"]["pass"] == "scoring"
    assert c["evidence"]["dimension_definition"].startswith("Depth of")
    assert "cited_evidence" in c["evidence"]
    assert "score" in c["evidence"]
    assert "SUPPORTED" in c["prompt"]["question"]
    assert str(_SYNTHETIC) in c["metadata"]["evidence_source"]
    # Unlabelled by construction — a human sets these before it becomes a real case.
    assert c["metadata"]["expected"].startswith("SET_ME")
    assert "RELABEL" in c["key"]
    # Applicant referenced by opaque index only — never the real application_id (42 / 7).
    assert "42" not in str(c)
    assert "applicant" in c["metadata"]["title"]


def test_opaque_index_hides_real_application_ids(db) -> None:
    run = _seed(db, _SYNTHETIC)
    cases = propose_cases(db, run)
    # ids 7 and 42 map to opaque 0 and 1 (sorted); no case leaks the raw id.
    sources = " ".join(c["metadata"]["evidence_source"] for c in cases)
    assert "idx 0" in sources
    assert "idx 1" in sources
    assert "42" not in sources
    assert "application_id" not in sources
