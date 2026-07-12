"""Shared compressed pool view for the pool-level AI passes (currently discovery).

The pass reasons over the whole eligible pool in one call and needs a compact
per-candidate view — structured facts plus the applicant's raw essays. Defined once
here so any pool-level pass provably reads the identical pool, the same anti-drift
discipline ``applicant_facts.py`` enforces between discovery and scoring: a change to
what the pool looks like changes it everywhere at once.

The pool view is structured facts plus the applicant's raw essay answers — the model
reads the essays directly rather than a pre-summarized digest.
"""

from __future__ import annotations

import json

from app.ai.applicant_facts import applicant_facts
from app.db.models import Application
from app.services.application_import import extract_essays

# Rough per-candidate input token weight for the pre-run cost estimate only (the
# real call is priced from actual usage). Tuned to the SPEC's observed ~$0.07-0.11
# for a ~32-candidate pool on the synthesis model.
INPUT_TOKENS_PER_CANDIDATE = 600


def candidate_digest(application: Application) -> dict:
    """One candidate's contribution to a pool prompt: structured facts plus the
    applicant's raw essays, kept compact so the whole pool fits one call. Facts and
    essays together surface both quantitative and qualitative axes.
    """
    essays = extract_essays(application.raw_row or {})
    return {
        "applicant_id": application.id,
        "facts": applicant_facts(application),
        "essays": [
            {"label": e.get("label"), "answer": e.get("answer")} for e in essays
        ],
    }


def pool_digest_block(applications: list[Application]) -> str:
    """The full ``<applicant_pool>`` prompt block for a pool-level pass: every
    application's compact digest, as pretty JSON wrapped in the XML tag.
    """
    digests = [candidate_digest(app) for app in applications]
    pool_json = json.dumps(digests, indent=2, default=str)
    return f"<applicant_pool>\n{pool_json}\n</applicant_pool>"
