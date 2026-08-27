"""Pure transformations that preserve dimension identity across ranking runs."""

from __future__ import annotations

from app.ai.schemas import PoolDimensionReport


def adopt_matched_keys(
    report: PoolDimensionReport,
    new_to_old: dict[str, str],
    prior: PoolDimensionReport | None,
) -> PoolDimensionReport:
    """Adopt a matched dimension's prior key and text, collapsing key collisions."""
    prior_by_key = {dimension.key: dimension for dimension in prior.dimensions} if prior else {}
    taken: set[str] = set()
    dimensions = []
    for dimension in report.dimensions:
        old_key = new_to_old.get(dimension.key)
        is_match = old_key is not None and old_key in prior_by_key
        if is_match:
            adopted = prior_by_key[old_key].model_copy(
                update={"from_committee_request": dimension.from_committee_request}
            )
        else:
            adopted = dimension
        if adopted.key in taken:
            continue
        taken.add(adopted.key)
        dimensions.append(adopted)
    return report.model_copy(update={"dimensions": dimensions})


def flatten_merges(merges: dict[str, str]) -> dict[str, str]:
    """Resolve every drop-to-keep chain to its terminal survivor."""
    flattened: dict[str, str] = {}
    for start, target in merges.items():
        seen = {start}
        while target in merges and target not in seen:
            seen.add(target)
            target = merges[target]
        flattened[start] = target
    return flattened


def transfer_merged_tiers(tiers: list[dict], merges: dict[str, str]) -> list[dict]:
    """Move each dropped key's placement to its survivor's highest-priority tier."""
    placement = {
        key: index
        for index, tier in enumerate(tiers)
        for key in tier.get("dimension_keys", [])
    }
    target_index: dict[str, int] = {}
    for dropped_key, survivor_key in merges.items():
        candidates = [
            placement[key]
            for key in (dropped_key, survivor_key)
            if key in placement
        ]
        if not candidates:
            continue
        best = min(candidates)
        previous = target_index.get(survivor_key, placement.get(survivor_key))
        target_index[survivor_key] = best if previous is None else min(previous, best)

    updated = [
        {
            **tier,
            "dimension_keys": [
                key
                for key in tier.get("dimension_keys", [])
                if key not in merges and target_index.get(key, index) == index
            ],
        }
        for index, tier in enumerate(tiers)
    ]
    for survivor_key, index in target_index.items():
        if index < len(updated) and survivor_key not in updated[index]["dimension_keys"]:
            updated[index]["dimension_keys"].append(survivor_key)
    return updated
