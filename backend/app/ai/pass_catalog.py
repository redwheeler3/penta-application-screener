"""Stable metadata for AI passes that have configurable models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AIPassSpec:
    key: str
    label: str
    model_attr: str
    reasoning_attr: str


AI_PASS_CATALOG = (
    AIPassSpec("screening", "Screening", "screening_model", "screening_reasoning_effort"),
    AIPassSpec("scoring", "Dimension scoring", "dimension_scoring_model", "dimension_scoring_reasoning_effort"),
    AIPassSpec("discovery", "Discovery", "discovery_model", "discovery_reasoning_effort"),
    AIPassSpec("decomposition", "Decomposition", "decompose_model", "decompose_reasoning_effort"),
    AIPassSpec("matching", "Matching", "match_model", "match_reasoning_effort"),
    AIPassSpec("consolidation", "Consolidation", "consolidate_model", "consolidate_reasoning_effort"),
)

AI_PASSES_BY_KEY = {spec.key: spec for spec in AI_PASS_CATALOG}


def ai_pass(key: str) -> AIPassSpec | None:
    return AI_PASSES_BY_KEY.get(key)
