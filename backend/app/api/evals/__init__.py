"""The in-UI eval cockpit (the Evals tab), split into a package by concern:
``catalog`` (free meta: catalog / invariants / re-baseline / last-run), ``cases`` (editing
golden cases + judge briefs), ``runs`` (the streaming pass runs + blind judge), over shared
plumbing in ``_shared``.

Thin HTTP over the eval RUNNERS in ``app.evals.*`` — the endpoints call the same functions the
CLI-less runners expose (``run_case``, ``judge_case``, ``stability_run``, ``run_invariants``),
so nothing is reimplemented; this maps runner dataclasses to the camelCase wire schemas, streams
the model's reasoning, and persists each run as an ``EvalRun`` row.

Dependency direction: evals → app, never app → evals. This package imports production plumbing
(the shared NDJSON event vocabulary, the provider); no production module imports anything here.
Evals are a consumer of the app, not part of its shipped runtime.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.evals import cases, catalog, runs

router = APIRouter(prefix="/evals", tags=["evals"])
router.include_router(catalog.router)
router.include_router(cases.router)
router.include_router(runs.router)
