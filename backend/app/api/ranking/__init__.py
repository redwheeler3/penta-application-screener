"""Ranking API: the Rank chain and the deterministic ranked shortlist.

Flow the UI drives:
  1. GET  /ranking/run/estimate — combined cost projection for the chain.
  2. POST /ranking/run — find criteria → score every eligible applicant, streaming
     phase/progress/summary as NDJSON. The cap is enforced once over the COMBINED cost
     before any model call.
  3. GET  /ranking/current — the current run's criteria + summary.
  4. GET  /ranking — the ranked shortlist (math over cached scores).
  5. GET/PUT /ranking/tiers — the committee's importance-tier weighting.
  6. PUT  /ranking/seeds — pending free-text proposals for the next run.

The committee never runs the three sub-passes individually, so they're exposed as
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

# The tag is set here; each sub-router carries the full ``/ranking`` prefix itself
# (FastAPI won't let a prefix-less child hold the empty-path root route ``GET /ranking``).
router = APIRouter(tags=["ranking"])
router.include_router(run.router)
router.include_router(score_current.router)
router.include_router(current.router)
router.include_router(shortlist.router)
