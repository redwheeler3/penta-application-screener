"""Ranking API: the Rank chain and the deterministic ranked shortlist.

Flow the UI drives:
  1. GET  /ranking/estimate — combined cost projection for the chain.
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
  - run.py       — the Rank chain + its cost estimates (the streaming ``rank_run``).
  - current.py   — the current run's criteria + the AI-legibility audits.
  - insights.py  — the Insights-tab read endpoints (cost / last-runs / metrics).
  - shortlist.py — the deterministic ranked list + tiers + discovery seeds.
"""

from fastapi import APIRouter

from app.api.ranking import current, insights, run, shortlist

# The tag is set here; each sub-router carries the full ``/ranking`` prefix itself
# (FastAPI won't let a prefix-less child hold the empty-path root route ``GET /ranking``).
router = APIRouter(tags=["ranking"])
router.include_router(run.router)
router.include_router(current.router)
router.include_router(insights.router)
router.include_router(shortlist.router)
