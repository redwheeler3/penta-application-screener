"""Structured output schemas — the shared contract between prompts, storage, the
API, and the UI for AI-assisted screening. One definition per shape keeps prompts,
caching, and rendering aligned.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class FlagCategory(StrEnum):
    PLACEHOLDER_NAME = "placeholder_name"
    SUSPICIOUS_NAME = "suspicious_name"
    MINIMAL_ESSAY = "minimal_essay"
    SPAM_ESSAY = "spam_essay"
    AI_GENERATED_ESSAY = "ai_generated_essay"
    DUPLICATED_ANSWERS = "duplicated_answers"
    INTERNAL_INCONSISTENCY = "internal_inconsistency"
    FAKE_CONTACT = "fake_contact"
    PET_POLICY = "pet_policy"
    OTHER = "other"


class FlagSeverity(StrEnum):
    INFO = "info"
    NOTABLE = "notable"


class ScreeningFlag(BaseModel):
    category: FlagCategory
    severity: FlagSeverity = Field(
        description="info for minor notes; notable for things the screener should review",
    )
    summary: str = Field(description="One-sentence, neutral description of the concern.")
    evidence: str = Field(
        description="Short quote or specific field reference supporting the flag. No full essays.",
    )


class ScreeningReport(BaseModel):
    """The complete set of informational screening flags for one application.

    Empty ``flags`` means the integrity pass found nothing of concern. Flags are
    never disqualifying — they only surface things for the screener to review.
    """

    flags: list[ScreeningFlag] = Field(default_factory=list)


# --- Pattern discovery and dimension scoring --------------------------------
#
# The LLM extracts scored features; ranking is deterministic math over them.
# Discovery finds how THIS pool varies; scoring rates each candidate on those
# dimensions. Both schemas have a fixed SHAPE; only which dimensions appear is open.


class PoolDimension(BaseModel):
    """One discovered axis along which this applicant pool meaningfully varies."""

    key: str = Field(
        description=(
            "Stable snake_case identifier, e.g. 'participation_commitment'. "
            "Used to tie each candidate's score back to this dimension, so it "
            "must be unique within the report and stable wording."
        )
    )
    name: str = Field(description="Short human-readable label for the committee UI.")
    definition: str = Field(
        description="1-2 sentences defining what this dimension measures, in neutral terms.",
    )
    high_end: str = Field(
        description=(
            "What a HIGH score (near 1.0) means — the most-desirable-fit end of this "
            "axis. Must be a concrete description of the applicant at that end, never "
            "'policy-dependent' or 'left to the committee': if you can't name a high "
            "end that is clearly better fit, this is a directionless quantity — reframe "
            "it to the fit concept it drives, or drop it (see the orientation rules)."
        ),
    )
    low_end: str = Field(
        description=(
            "What a LOW score (near 0.0) means — the opposite pole from high_end. "
            "Concrete, and the genuine inverse of the high end."
        ),
    )
    why_it_differentiates: str = Field(
        description=(
            "Briefly, why this dimension actually separates THIS pool — what "
            "varies across candidates here, not a generic ideal."
        )
    )
    from_committee_request: bool = Field(
        default=False,
        description=(
            "Set true ONLY for a dimension you created in response to a committee "
            "request (a favourited or proposed axis the prompt asked you to "
            "consider). A dimension you discovered on your own stays false. If one "
            "request splits into several dimensions, mark each of them true."
        ),
    )


class PoolDimensionReport(BaseModel):
    """Pool-level discovery: the differentiating dimensions for THIS pool.

    Run-scoped, not per-candidate. It does not rank, score, or weight anyone —
    importance is the committee's call. Scoring rates each applicant against these
    dimensions; ranking is deterministic math on top.

    Deliberately no pool ``summary`` / "what distinguishes strong from weak fit" field:
    the decomposition step that finalizes these dimensions never sees the pool, so any
    such digest would be an ungrounded pool claim (confabulation). Dimensions only.
    """

    dimensions: list[PoolDimension] = Field(
        default_factory=list,
        description=(
            "The discovered dimensions. Keep to the few that genuinely "
            "differentiate this pool — not an exhaustive rubric."
        ),
    )


class ScoreConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class JudgeVerdict(StrEnum):
    """A manual eval judge's semantic verdict.

    One enum across eval case families, paired by the task each case poses:
    consolidation/decomposition merges (MERGE/KEEP), decomposition routing drift
    (MATCHES/MISMATCHES), and dimension-score defensibility (SUPPORTED/UNSUPPORTED —
    does the cited evidence support the score?). Future steps add their own pair
    (e.g. screening flag support) on the same pattern.
    """

    MERGE = "merge"
    KEEP = "keep"
    MATCHES = "matches"
    MISMATCHES = "mismatches"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    FLAG_SUPPORTED = "flag_supported"
    FLAG_UNSUPPORTED = "flag_unsupported"


class JudgeReport(BaseModel):
    """One non-gating judgement over a labelled eval case."""

    verdict: JudgeVerdict
    reason: str = Field(description="One concise, evidence-based explanation.")


class DimensionScore(BaseModel):
    """One candidate's score on one discovered dimension, with grounding."""

    dimension_key: str = Field(
        description="The PoolDimension.key this score is for. Must match a discovered dimension.",
    )
    score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "How strongly this candidate exhibits the dimension, 0..1, judged "
            "only on stated evidence. Absence of evidence is a low score, not a "
            "guess."
        ),
    )
    rationale: str = Field(
        description="One neutral sentence explaining the score from what the applicant said.",
    )
    evidence: str = Field(
        description="Short quote or field reference grounding the score. No full essays. Empty if nothing stated.",
    )
    confidence: ScoreConfidence = Field(
        description=(
            "How well the evidence pins down the applicant's TRUE standing on "
            "this dimension — not how sure you are about what they wrote. A "
            "dimension the applicant did not address is LOW confidence even when "
            "you are certain it went unmentioned: silence is weak evidence, since "
            "they may have the strength and simply not have stated it."
        ),
    )


class DimensionScoringReport(BaseModel):
    """One candidate scored against the run's discovered dimensions — exactly one
    DimensionScore per dimension. Informational; never touches status. The scores
    are the support for ranking, behind committee-facing labels and rationale.
    """

    scores: list[DimensionScore] = Field(
        default_factory=list,
        description="One entry per discovered dimension, scoring this candidate on it.",
    )


class DimensionMatch(BaseModel):
    """One identity match between a freshly-discovered dimension and a prior one.

    On a re-rank, maps each NEW dimension onto the prior dimension it is the *same
    concept* as, so tier placement and cached scores carry forward. A pure identity
    judgment, never a weighting. High bar: match only when they mean the same thing.
    """

    new_key: str = Field(
        description="The key of a dimension in the NEW (just-discovered) set.",
    )
    old_key: str = Field(
        description=(
            "The key of the PRIOR-run dimension that means the same thing as "
            "new_key. Only include a pair when they are clearly the same concept."
        ),
    )


class DimensionMatchReport(BaseModel):
    """The high-confidence identity matches from new dimensions to prior ones,
    strictly one-to-one. Unmatched new dimensions are absent — they start in Ignore
    for the committee to triage. Absence is safe (a missed match costs a re-drag; a
    wrong match would move tier intent onto the wrong concept).
    """

    matches: list[DimensionMatch] = Field(
        default_factory=list,
        description=(
            "High-confidence identity matches only. Omit any new dimension you are "
            "not confident maps to a specific prior dimension."
        ),
    )


class ConsolidationVerdict(BaseModel):
    """One adjudicated candidate pair for the post-score consolidation pass.

    Score-vector correlation NOMINATES a pair (two dimensions whose per-applicant
    scores move near-identically); this verdict is the model deciding, from the
    definitions, whether they are the SAME concept (a duplicate to merge) or a
    CONFOUND (distinct axes that happen to correlate — e.g. two things engaged
    applicants both score high on). Merge only on same-concept: an over-merge loses a
    real distinction invisibly, the higher-stakes error.
    """

    key_a: str = Field(description="One dimension key from the nominated pair.")
    key_b: str = Field(description="The other dimension key from the nominated pair.")
    same_concept: bool = Field(
        description=(
            "True only if the two definitions measure the SAME underlying concept "
            "(a duplicate to merge). False if they are distinct axes that merely "
            "correlate (a confound) — when unsure, false; a wrong merge is unrecoverable."
        ),
    )
    reason: str = Field(
        description=(
            "One sentence: for same_concept, assert they'd score an applicant alike "
            "and are one axis; for a confound, name the applicant who'd score high on "
            "one and low on the other."
        ),
    )


class ConsolidationReport(BaseModel):
    """Verdicts for the correlation-nominated pairs. Only same_concept=true pairs are
    merged (loser aliased to the older/canonical key). Absence of a pair = keep apart.
    """

    verdicts: list[ConsolidationVerdict] = Field(
        default_factory=list,
        description="One verdict per nominated pair. Judge each on its definitions.",
    )


# --- Fan-out decomposition (SPEC "Fan-Out Redesign", Phase 3) ----------------
#
# K parallel discovery calls produce K reports that carve the same pool at
# different, overlapping granularities. The decomposition step sees all K at once
# and settles the FINEST set of axes that are each genuinely differentiating AND
# mutually non-overlapping — collapsing re-carvings of one concept, keeping
# genuinely distinct axes apart. Two-sided failure to guard: UNDER-merge (keep
# nine "participation" slices → weight one concept 9×) and OVER-merge (collapse a
# nurse's health-safety into a treasurer's finance → lose a real lever).


class DecomposedDimension(BaseModel):
    """One axis in the settled set, plus the provenance + reasoning that put it there.

    Carries the committee-facing IDENTITY fields (``key``, ``name``, ``definition``)
    plus ``source_keys`` — every input dimension (across the K reports) this axis
    subsumes — and ``decision`` reasoning, so a merge is auditable and never silent. A
    kept-as-is axis has one source key; a merge has several.

    Deliberately no ``why_it_differentiates``: that field is a claim about what varies
    across the REAL pool, but the decomposer is sent only the K reports'
    key/name/definition, never the pool — so any ``why`` it wrote would be ungrounded
    (confabulation). The pool-grounded ``why`` is written by the discoverer that read the
    essays, and ``to_pool_report`` carries it forward from the primary source axis.
    """

    key: str = Field(
        description=(
            "Stable snake_case identifier for the settled axis. Prefer REUSING an "
            "input dimension's key when this axis is essentially that one; mint a new "
            "snake_case key only for a genuinely new merged concept. Unique within the set."
        )
    )
    name: str = Field(description="Short human-readable label for the committee UI.")
    definition: str = Field(
        description="1-2 neutral sentences defining what this settled axis measures.",
    )
    high_end: str = Field(
        description=(
            "What a HIGH score (near 1.0) means — the most-desirable-fit end. Carry it "
            "forward from the source axes; never 'policy-dependent' or 'left to the "
            "committee'. A directionless quantity should have been reframed or split in "
            "discovery, not settled as one axis with an undefined high end."
        ),
    )
    low_end: str = Field(
        description="What a LOW score (near 0.0) means — the opposite pole from high_end.",
    )
    source_keys: list[str] = Field(
        default_factory=list,
        description=(
            "Every input dimension key (from any of the K reports) this settled axis "
            "subsumes. One key = kept essentially as-is; several = a merge of "
            "re-carvings of one concept. List ALL absorbed keys — this is the merge "
            "audit trail and the only way a swallowed axis stays visible."
        ),
    )
    from_committee_request: bool = Field(
        default=False,
        description=(
            "True if ANY source dimension was committee-requested (a proposed/"
            "favourited axis). A committee request must never be silently merged away, "
            "so this flag rides through a merge — see decision reasoning if it was folded."
        ),
    )
    decision: str = Field(
        description=(
            "One or two sentences on WHY these source axes are one settled axis (for a "
            "merge, assert they would score the same applicant the same way) or why "
            "this axis is kept distinct. The audit trail for over/under-merge review."
        ),
    )


class DecompositionReport(BaseModel):
    """The settled, finest-non-overlapping dimension set distilled from K discovery
    reports (SPEC "Fan-Out Redesign", Phase 3), with the reasoning behind every merge.

    Every input dimension key across the K reports MUST appear in exactly one settled
    dimension's ``source_keys`` — nothing is silently dropped; a genuinely redundant
    carving is merged (recorded), never deleted. The result feeds scoring once.

    No pool ``summary`` field (see ``PoolDimensionReport`` for why the decomposer emits
    dimensions only, not a pool digest).
    """

    dimensions: list[DecomposedDimension] = Field(
        default_factory=list,
        description=(
            "The settled axes: the finest set that is each differentiating AND "
            "non-overlapping. Split a concept only where a plausible applicant lands "
            "high on one part and low on another; merge only true re-carvings."
        ),
    )


