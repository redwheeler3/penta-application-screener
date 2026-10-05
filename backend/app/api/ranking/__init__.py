"""Ranking API: the Rank chain and the deterministic ranked shortlist.

Flow the UI drives:
  1. GET  /ranking/run/estimate — combined cost projection for the chain.
  2. POST /ranking/run — find criteria → score every eligible applicant, streaming
     phase/progress/summary as NDJSON. The cap is enforced once over the COMBINED cost
     before any model call.
  3. GET  /ranking/current — the current run's criteria + summary.
  4. GET  /ranking/board — coherent criteria, ranked applicants, and tier layout.
  5. PUT  /ranking/tiers — the committee's importance-tier weighting.
  6. PATCH /ranking/proposals — individual Add/Remove intent for pending proposals.

The committee never runs the individual AI passes separately, so they're exposed as
one Rank step; the passes stay separate underneath (distinct schemas, cache kinds,
status behavior).

Split by what each file owns (all under the ``/ranking`` prefix):
  - run.py           — estimate and start a full Rank run;
  - score_current.py — estimate and fill only missing scores;
  - current.py       — current criteria + the AI-legibility audits;
  - shortlist.py     — deterministic ranked list + tiers + discovery seeds.

The streamed criteria → scoring → consolidation orchestration lives in
``app/services/ranking/pipeline.py``.

Cross-run Observability reads (cost / last-runs / metrics) are NOT here — they span Screen,
Rank, and score-current, so they live at top-level ``/observability`` (``app/api/observability.py``).
"""

from fastapi import APIRouter

from app.api.ranking import current, run, score_current, shortlist

router = APIRouter(prefix="/ranking", tags=["ranking"])
router.include_router(run.router)
router.include_router(score_current.router)
router.include_router(current.router)
router.include_router(shortlist.router)
