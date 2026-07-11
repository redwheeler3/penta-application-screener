"""One-shot data cleanup: remove decomposer-fabricated `why_it_differentiates` from
stored runs (SPEC "Fan-Out Redesign", Validation 0 — the confabulation fix).

Background. Before commit 2eb1d18, the decomposer WROTE each settled axis's
`why_it_differentiates` — but it is sent only the K reports' key/name/definition, never
the pool, so those whys were confident, plausible, and unverifiable (confabulation).
The code fix stops generating them going forward and carries the pool-grounded why
forward from each axis's primary source discoverer. But the fabricated whys are already
baked into stored runs, and the match pass adopts a prior axis's text wholesale — so a
matched axis would keep pulling the old slop forward indefinitely. This scrubs it.

Scope. Only runs with a `decompose_audit` (the decomposer-era marker) are affected;
pre-decomposer runs (no `decompose_audit`) have real discoverer whys and are left alone.
For each affected run:
  - **Regenerate** every stored dim's why from `fan_out_audit` — the discoverer that
    coined the axis read the pool, so its why is the real one. Resolved via the settled
    axis's `source_keys` (decompose_audit), bridged through the match rename
    (`match_audit.new_to_old`, since stored keys are POST-match but source_keys are PRE).
  - **Blank** (empty string) any why that can't be regenerated — the earliest fan-out
    runs (11-12) predate per-discoverer report capture (`fan_out_audit.passes` empty), so
    there is no source to recover from. An empty why renders as nothing in the UI (honest
    absence) rather than fabricated presence — the new contract: grounded or absent, never
    invented.

Idempotent: re-running regenerates to the same grounded whys and re-blanks the same
unrecoverable ones. No runtime code path is left behind — this is a migration, run once.

    cd backend && uv run python -m scripts.fix_decomposer_why          # dry run (report)
    cd backend && uv run python -m scripts.fix_decomposer_why --write  # apply
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.db.models import RankingRun
from app.db.session import SessionLocal


def _discoverer_why_by_key(criteria: dict) -> dict[str, str]:
    """key -> the discoverer's pool-grounded why, from this run's fan_out_audit.
    First non-empty writer wins (a key repeated across K reports keeps report 0's why).
    """
    out: dict[str, str] = {}
    for p in (criteria.get("fan_out_audit") or {}).get("passes") or []:
        for d in (p.get("report") or {}).get("dimensions") or []:
            why = d.get("why_it_differentiates") or ""
            if why and d.get("key") not in out:
                out[d["key"]] = why
    return out


def _source_keys_by_stored_key(criteria: dict) -> dict[str, list[str]]:
    """Stored (POST-match) dim key -> the discoverer source keys that fed it.

    decompose_audit.settled is keyed by the PRE-match key and lists source_keys; the
    match pass then renamed some settled keys to adopt prior keys (match_audit.new_to_old
    maps PRE -> POST). We invert that to map each stored POST key back to its source_keys.
    """
    settled = (criteria.get("decompose_audit") or {}).get("settled") or []
    sources_by_pre = {d["key"]: d.get("source_keys", []) for d in settled}
    new_to_old = (criteria.get("match_audit") or {}).get("new_to_old") or {}
    pre_by_post = {post: pre for pre, post in new_to_old.items()}
    out: dict[str, list[str]] = {}
    for pre_key, sources in sources_by_pre.items():
        post_key = new_to_old.get(pre_key, pre_key)
        out[post_key] = sources
    # A stored key that never appears in decompose_audit (shouldn't happen) still resolves
    # to itself below via the .get fallback.
    _ = pre_by_post
    return out


def _grounded_why(stored_key: str, why_by_key: dict[str, str], sources_by_key: dict[str, list[str]]) -> str | None:
    """The grounded why for a stored dim: the first source key (or the key itself) that
    has a discoverer why. None if nothing resolves (unrecoverable → caller blanks it)."""
    candidates = sources_by_key.get(stored_key, [stored_key]) or [stored_key]
    for key in candidates:
        if why_by_key.get(key):
            return why_by_key[key]
    # Last resort: the stored key might directly match a discoverer key.
    return why_by_key.get(stored_key) or None


def main() -> None:
    write = "--write" in sys.argv
    db = SessionLocal()
    runs = list(db.scalars(select(RankingRun).order_by(RankingRun.id.asc())))

    affected = [r for r in runs if (r.criteria or {}).get("decompose_audit")]
    print(f"\n{'=' * 70}")
    print(f"FIX DECOMPOSER WHY — {'WRITE' if write else 'DRY RUN'}")
    print(f"  {len(affected)} decomposer-era run(s) to scrub; "
          f"{len(runs) - len(affected)} pre-decomposer run(s) left alone")
    print(f"{'=' * 70}")

    total_regen = total_blank = 0
    for run in affected:
        criteria = dict(run.criteria or {})
        report = dict(criteria.get("dimension_report") or {})
        dims = [dict(d) for d in report.get("dimensions") or []]
        why_by_key = _discoverer_why_by_key(criteria)
        sources_by_key = _source_keys_by_stored_key(criteria)

        regen = blank = 0
        for d in dims:
            grounded = _grounded_why(d["key"], why_by_key, sources_by_key)
            if grounded is not None:
                if d.get("why_it_differentiates") != grounded:
                    d["why_it_differentiates"] = grounded
                regen += 1
            else:
                d["why_it_differentiates"] = ""  # unrecoverable → honest blank
                blank += 1

        total_regen += regen
        total_blank += blank
        print(f"  run {run.id:>3}: {regen:>2} regenerated, {blank:>2} blanked "
              f"({'no per-discoverer data' if blank and not why_by_key else 'ok'})")

        if write:
            report["dimensions"] = dims
            criteria["dimension_report"] = report
            run.criteria = criteria  # reassign so SQLAlchemy tracks the JSON change

    if write:
        db.commit()
        print(f"\n  committed: {total_regen} whys regenerated, {total_blank} blanked.")
    else:
        print(f"\n  dry run: would regenerate {total_regen}, blank {total_blank}. "
              f"Re-run with --write to apply.")
    db.close()


if __name__ == "__main__":
    main()
