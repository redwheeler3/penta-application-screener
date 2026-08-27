"""Audit-view builders: stored AI reasoning → trace-viewer payloads.

Each Rank pass (fan-out discovery → decompose → identity-match → consolidate) persists its
raw reasoning on the analysis's 1:1 ``AnalysisAudit`` row. These read-only accessors shape
that stored audit into the payloads the Observability trace viewer renders — deriving a few
display-only fields (carry-forward rate, source-report labels, resolved dimension names) and
tolerating older analyses that predate a given pass (each returns None rather than raising).

This is view-shaping, distinct from ``analysis.py``'s persistence + member-view derivation;
it depends on that module only for ``key_history`` (dimension-name resolution).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Analysis
from app.services.analysis import key_history


def _audit_field(analysis: Analysis, name: str) -> dict | None:
    """One field off the analysis's 1:1 audit row (``match``/``decompose``/``consolidate``/
    ``fan_out``), or None when it has no audit row (predates the split) — so the audit-view
    accessors don't each repeat the ``analysis.audit.<field> if analysis.audit`` guard.
    """
    return getattr(analysis.audit, name) if analysis.audit else None


def match_audit_view(analysis: Analysis) -> dict | None:
    """The analysis's carry-forward audit, shaped for the trace viewer, or None when it
    predates match-audit capture (older analyses stored no audit).

    The stored audit (``analysis.audit.match``) records what discovery *actually*
    emitted before ``adopt_matched_keys`` rewrote matched keys, plus the new→old map
    and the match narrative. This adds the derived **carry-forward rate** (matched /
    discovered) — a persistently near-100% rate is the smell that the match pass is
    over-matching. ``carry_forward_rate`` is None on a first run, where there were no
    prior dimensions to match against and the rate is undefined (not zero).
    """
    audit = _audit_field(analysis, "match")
    if not audit:
        return None
    discovered = audit.get("raw_discovery_dimensions", [])
    new_to_old = audit.get("new_to_old", {}) or {}
    prior_names = audit.get("prior_dimension_names", {}) or {}
    matched = len(new_to_old)
    is_first_run = not audit.get("prior_dimension_count", 0)
    # Resolve each matched new-key to the prior dimension it adopted: its prior key and
    # (when known — older audits lack the names map) the prior user-facing name. Lets
    # the viewer show the prior title alongside the key, mirroring the discovered column.
    new_to_old_named = {
        new_key: {"key": old_key, "name": prior_names.get(old_key)}
        for new_key, old_key in new_to_old.items()
    }
    return {
        "raw_discovery_dimensions": discovered,
        "new_to_old": new_to_old_named,
        "match_narrative": audit.get("match_narrative"),
        "prior_dimension_count": audit.get("prior_dimension_count", 0),
        "discovered_count": len(discovered),
        "matched_count": matched,
        "new_count": len(discovered) - matched,
        # Fraction of newly-discovered dimensions the match pass mapped onto a prior
        # one. None (not 0.0) on a first run — nothing to match against.
        "carry_forward_rate": (
            None if is_first_run or not discovered else round(matched / len(discovered), 4)
        ),
    }


def decompose_audit_view(analysis: Analysis) -> dict | None:
    """The analysis's decompose audit — how the K fan-out reports were settled into one set —
    shaped for the trace viewer, or None on analyses that predate decomposition (single-
    discovery runs have no ``analysis.audit.decompose``).

    The stored audit (built by ``dimension_decomposition.decompose_audit_payload``) is already
    view-shaped: settled axes with source_keys + decision reasoning, the input/settled
    counts, and the D9 ``folded_requests`` trail. This is a thin pass-through with
    defaults, mirroring the other ``*_audit_view`` accessors so the router stays uniform.
    """
    audit = _audit_field(analysis, "decompose")
    if not audit:
        return None
    # Which discovery report(s) coined each source key, derived from the fan-out audit
    # (source key -> [report index]). A key in several reports = independent re-discovery.
    # Empty on runs whose fan-out wasn't captured; the UI then just omits the R-labels.
    # Same pass also collects each source key's user-facing name (source key -> name), so
    # the panel can show a merge's inputs by name, not just key. A key absent here (fan-out
    # uncaptured) simply has no name entry; the UI falls back to the bare key.
    key_to_reports: dict[str, list[int]] = {}
    key_to_name: dict[str, str] = {}
    fan_out = _audit_field(analysis, "fan_out") or {}
    for i, p in enumerate(fan_out.get("passes", [])):
        for dim in (p.get("report") or {}).get("dimensions", []):
            key_to_reports.setdefault(dim.get("key"), []).append(i)
            key_to_name.setdefault(dim.get("key"), dim.get("name", ""))
    settled = [
        {
            **s,
            "source_report_map": {
                sk: key_to_reports[sk] for sk in s.get("source_keys", []) if sk in key_to_reports
            },
            "source_names": {
                sk: key_to_name[sk] for sk in s.get("source_keys", []) if sk in key_to_name
            },
        }
        for s in audit.get("settled", [])
    ]
    return {
        "input_report_count": audit.get("input_report_count", 0),
        "input_dimension_count": audit.get("input_dimension_count", 0),
        "settled_count": audit.get("settled_count", 0),
        "merge_count": audit.get("merge_count", 0),
        "settled": settled,
        "folded_requests": audit.get("folded_requests", []),
        "narrative": audit.get("narrative"),
    }


def consolidate_audit_view(db: Session, analysis: Analysis) -> dict | None:
    """The analysis's consolidation audit — the correlation-nominated duplicate pairs and the
    confirm verdict on each — shaped for the trace viewer, or None on analyses that predate
    the pass (no ``analysis.audit.consolidate``).

    ``pairs`` are every nominated pair with its keep/drop keys + user-facing names, the
    correlation ``r``, whether it ``merged``, and the model's ``reason``. ``merges`` (the
    applied ``drop_key -> keep_key`` map) is DERIVED from the merged pairs — it isn't stored
    twice; the durable merge-truth is the ``dimension_aliases`` table, and this view is the
    per-analysis record of what the pass decided.

    Names prefer the value SNAPSHOTTED into the pair at consolidation time (the durable
    record — a merged drop key leaves the report, so its name can't be looked up later),
    falling back to the key's name from history/this analysis's own artifacts. The fallback
    covers pairs written before name capture existed: a prior key resolves via its MINT name
    across all reports; a key minted AND retired within THIS analysis (so never in any report)
    resolves via this analysis's own decompose/fan-out names. Only a key with no trace anywhere
    stays nameless, and the UI then shows the bare key.
    """
    audit = _audit_field(analysis, "consolidate")
    if not audit:
        return None
    # Resolution map: cross-analysis mint names, then overlaid with this analysis's own
    # settled + discovered names (covers a within-run mint-then-retire never in a report).
    _rank, _defs, names = key_history(db)
    resolve = dict(names)
    # `or {}` on each audit: they're stored as null on analyses that predate that pass.
    for s in (_audit_field(analysis, "decompose") or {}).get("settled", []):
        resolve.setdefault(s.get("key"), s.get("name", ""))
    for p in (_audit_field(analysis, "fan_out") or {}).get("passes", []):
        for dim in (p.get("report") or {}).get("dimensions", []):
            resolve.setdefault(dim.get("key"), dim.get("name", ""))
    pairs = [
        {
            **p,
            # Snapshot first (truthy), then resolved name, then "" (UI → bare key).
            "keep_name": p.get("name_keep") or resolve.get(p.get("keep"), ""),
            "drop_name": p.get("name_drop") or resolve.get(p.get("drop"), ""),
        }
        for p in audit.get("pairs", [])
    ]
    return {
        # Derived from the merged pairs, not stored — dimension_aliases is the merge-truth.
        "merges": {p["drop"]: p["keep"] for p in pairs if p.get("merged")},
        "pairs": pairs,
        "nominated_count": len(pairs),
        "merged_count": sum(1 for p in pairs if p.get("merged")),
        "narrative": audit.get("narrative"),
    }


def fan_out_audit_view(analysis: Analysis) -> dict | None:
    """The analysis's fan-out audit — each of the K parallel discoverers' report + reasoning —
    shaped for the Observability discovery panel, or None on analyses that predate the fan-out
    (single-discovery runs have no ``analysis.audit.fan_out``, or an older shape).

    Returns ``{k, passes: [{dimensions: [{key,name,definition,why...}], narrative}]}``.
    Older audits stored ``reports`` without per-pass narratives; those are tolerated
    (narrative comes back null) so the panel still renders their dimensions. Any extra
    keys in a stored report are ignored — only the fields above are projected.
    """
    audit = analysis.audit.fan_out if analysis.audit else None
    if not audit:
        return None
    # Current shape: passes = [{report, narrative}]. Legacy shape: reports = [report].
    raw_passes = audit.get("passes")
    if raw_passes is None:
        raw_passes = [{"report": r, "narrative": None} for r in audit.get("reports", [])]

    passes = []
    for p in raw_passes:
        report = p.get("report") or {}
        passes.append(
            {
                "dimensions": [
                    {
                        "key": d.get("key", ""),
                        "name": d.get("name", ""),
                        "definition": d.get("definition", ""),
                        "why_it_differentiates": d.get("why_it_differentiates", ""),
                    }
                    for d in report.get("dimensions", [])
                ],
                "narrative": p.get("narrative"),
            }
        )
    return {"k": audit.get("k", len(passes)), "passes": passes}
