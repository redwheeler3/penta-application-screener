"""Per-dimension score vectors + their pairwise correlation — the shared signal for
detecting when two dimensions are the same axis re-carved.

Every scored dimension has a vector of per-applicant -1..+1 scores. Two carvings of one
concept move together candidate by candidate (high Pearson r); two genuinely distinct
axes need not. High r is a *flag to inspect*, never an automatic verdict — a pair can
correlate for a real reason (two distinct skills both tracking "high-agency applicant"),
so definitions remain the ground truth. Used by the post-score consolidation pass (which
nominates high-r pairs, then confirms by definition) and the read-only overlap script.
"""

from __future__ import annotations

from math import sqrt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.dimension_scoring import KIND_PREFIX
from app.db.models import ApplicationAIResult, ApplicationAISelection

# Correlation at/above which a dimension pair is nominated as a suspected duplicate.
# Default 0.8 catches subtler forks. A nomination is followed by a definition-based
# confirm, never an auto-merge. A tunable knob.
CORRELATION_THRESHOLD = 0.8

# A correlation needs at least this many candidates scored on BOTH dimensions to mean
# anything (a 2-point "line" always correlates perfectly).
MIN_SUPPORT = 3


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation of two equal-length vectors, or None when undefined
    (fewer than 2 points, or either vector constant — a flat axis has no correlation
    to speak of, and moves no ranking, so it simply isn't flagged).
    """
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    cov = sum(a * b for a, b in zip(dx, dy))
    var_x = sum(a * a for a in dx)
    var_y = sum(b * b for b in dy)
    if var_x == 0.0 or var_y == 0.0:
        return None
    return cov / sqrt(var_x * var_y)


def load_score_vectors(
    db: Session, *, application_ids: list[int] | None = None, dimension_keys: list[str] | None = None,
) -> dict[str, dict[int, float]]:
    """Every selected dimension key → {consumer application_id: selected score}.

    Uses the same selected results as the ranker. First-seen criterion order is
    preserved across cache changes; history and narratives stay in the DB.
    """
    first_seen_order = {
        "partition_by": ApplicationAIResult.kind,
        "order_by": (ApplicationAIResult.created_at, ApplicationAIResult.id),
    }
    history = (
        select(
            ApplicationAIResult.id,
            ApplicationAIResult.kind,
            ApplicationAIResult.producer_application_id,
            ApplicationAIResult.output,
            func.first_value(ApplicationAIResult.created_at).over(**first_seen_order).label("first_seen_at"),
            func.first_value(ApplicationAIResult.id).over(**first_seen_order).label("first_seen_id"),
        )
        .where(ApplicationAIResult.kind.like(f"{KIND_PREFIX}:%"))
        .subquery()
    )
    query = (select(history.c.kind, ApplicationAISelection.application_id, history.c.output)
        .join(ApplicationAISelection, ApplicationAISelection.result_id == history.c.id)
        # Equal correlations retain criterion order in the nomination list and model prompt.
        .order_by(history.c.first_seen_at, history.c.first_seen_id, ApplicationAISelection.application_id))
    if application_ids is not None:
        query = query.where(ApplicationAISelection.application_id.in_(application_ids))
    if dimension_keys is not None:
        query = query.where(history.c.kind.in_([f"{KIND_PREFIX}:{key}" for key in dimension_keys]))
    rows = db.execute(query)
    vectors: dict[str, dict[int, float]] = {}
    for kind, application_id, output in rows:
        key = kind.split(":", 1)[1]  # strip the "dimension_scoring:" prefix
        score = float((output or {}).get("score", 0.0))
        vectors.setdefault(key, {})[application_id] = score
    return vectors


def correlation(a: str, b: str, vectors: dict[str, dict[int, float]]) -> float | None:
    """Pearson r of two keys' score vectors over the candidates scored on both, or
    None if they share fewer than ``MIN_SUPPORT`` candidates or either is flat.
    """
    va, vb = vectors.get(a), vectors.get(b)
    if not va or not vb:
        return None
    common = sorted(va.keys() & vb.keys())
    if len(common) < MIN_SUPPORT:
        return None
    return pearson([va[c] for c in common], [vb[c] for c in common])
