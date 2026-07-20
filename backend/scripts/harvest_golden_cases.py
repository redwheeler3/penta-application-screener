"""A MANUAL harvest aid: propose golden-case CANDIDATES for the thin eval files from a real
run's persisted audits.

The categorical eval files (decomposition, matching) are thin, and good golden cases must be
EXACT slices of real runs — not hand-fabricated (a lost run stays lost; see docs/ai-evals.md).
This scans the newest ranking run's ``decompose_audit`` (settled folds) and the discovery
definitions the decomposer saw (``fan_out_audit``), and PRINTS candidates already shaped as the
golden envelope (see docs/eval-case-schema.md), with the model's own ``decision`` pre-filled as
``label_rationale``.

Like the ``capture_*`` harvesters (app/evals/), this PROPOSES only — a human picks the
instructive ones, sets ``note``, confirms the ``expected`` label, and commits them into the
``<pass>_golden.json`` files. It never writes fixtures itself. Run by hand:

    python -m scripts.harvest_golden_cases [decomposition|matching|all]

Operator diagnostic, so it lives in ``scripts/`` (no runtime caller). NOTE: it reads the run's
``criteria`` blob directly — the 129KB catch-all flagged for schema cleanup (SPEC docket); when
that lands, point the audit reads at the rationalized home.
"""

from __future__ import annotations

import json
import sys


def _source_defs(crit: dict) -> dict[str, dict]:
    """Every dimension definition seen this run, keyed by key — the raw text a decomposition
    ``source_key`` (or a matching pair) resolves back to. Discovery reports first (what the
    decomposer actually saw), then the settled report as a fallback."""
    defs: dict[str, dict] = {}
    for p in (crit.get("fan_out_audit") or {}).get("passes", []):
        for d in p.get("report", {}).get("dimensions", []):
            defs.setdefault(d["key"], d)
    for d in (crit.get("dimension_report") or {}).get("dimensions", []):
        defs.setdefault(d["key"], d)
    return defs


def _descriptor(defs: dict[str, dict], key: str) -> dict:
    d = defs.get(key, {})
    return {"key": key, "name": d.get("name", key), "definition": d.get("definition", "MISSING — not in this run's reports")}


def decomposition_candidates(crit: dict, defs: dict[str, dict]) -> None:
    """A decomposition case = each source-key definition as its own one-dim discovery report +
    expected merge (>1 carving folded to one axis) / keep (a settled axis of a single source)."""
    print("\n########## DECOMPOSITION candidates (settled folds) ##########")
    for s in (crit.get("decompose_audit") or {}).get("settled", []):
        keys = s["source_keys"]
        expected = "merge" if len(keys) > 1 else "keep"
        print("\n# " + f"{expected.upper()} · {s['key']} ({len(keys)} carving(s))")
        print(json.dumps({
            "key": f"HARVEST_{s['key']}_{expected}",
            "metadata": {"note": "SET_ME", "pass": "decomposition", "expected": expected,
                         "label_rationale": s.get("decision", ""), "source": "harvested from a real run's decompose_audit"},
            "given": {"reports": [[_descriptor(defs, k)] for k in keys]},
        }, indent=2, ensure_ascii=False))


def matching_candidates(crit: dict, defs: dict[str, dict]) -> None:
    """A matching case = a prior+new descriptor pair the pipeline treated as the SAME concept
    (a 'matches' case), mined from a decompose fold's first two distinct-text carvings — exactly
    the same-concept-different-wording pairs the identity-match pass exists to catch."""
    print("\n########## MATCHING candidates (same-concept, different-wording pairs) ##########")
    for s in (crit.get("decompose_audit") or {}).get("settled", []):
        real = [k for k in s["source_keys"] if defs.get(k, {}).get("definition")]
        distinct = []
        for k in real:  # keep only keys with distinct definition text (an identical pair is a trivial match)
            if all(defs[k]["definition"] != defs[j]["definition"] for j in distinct):
                distinct.append(k)
        if len(distinct) < 2:
            continue
        a, b = distinct[0], distinct[1]
        print("\n# " + f"matches · {a} ~ {b}")
        print(json.dumps({
            "key": f"HARVEST_{a}__{b}_matches",
            "metadata": {"note": "SET_ME", "pass": "matching", "expected": "matches",
                         "label_rationale": f"Folded into one axis ({s['key']}) by decomposition — {s.get('decision', '')}",
                         "source": "harvested from a real run's decompose_audit source pair"},
            "given": {"prior": [_descriptor(defs, a)], "new": [_descriptor(defs, b)]},
        }, indent=2, ensure_ascii=False))


def main() -> None:
    from sqlalchemy import select

    from app.db.models import RankingRun
    from app.db.session import SessionLocal

    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    db = SessionLocal()
    try:
        run = db.scalars(select(RankingRun).order_by(RankingRun.id.desc())).first()
        if run is None:
            print("No ranking runs to harvest from.")
            return
        crit = run.criteria or {}
        defs = _source_defs(crit)
        print(f"Harvesting from run {run.id} ({run.name}) — {len(defs)} dimension definitions in scope.")
        print("Candidates below are UNLABELLED proposals: pick the instructive ones, set `note`, "
              "confirm `expected`, drop the HARVEST_ key prefix, and commit into the golden file.")
        if which in ("all", "decomposition"):
            decomposition_candidates(crit, defs)
        if which in ("all", "matching"):
            matching_candidates(crit, defs)
    finally:
        db.close()


if __name__ == "__main__":
    main()
