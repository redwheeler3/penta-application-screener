from pydantic import Field, field_validator

from app.ai.model_catalog import (
    ModelProvider,
    ReasoningEffort,
    model_spec,
    supports_reasoning_effort,
)

# Threshold defaults are owned by the domain layer (the single source of truth);
# the settings schema references them so a default can't drift between the two.
from app.domain.hard_filters import (
    DEFAULT_ALLOW_OTHER_PETS,
    DEFAULT_MAX_CATS,
    DEFAULT_MAX_CHILD_AGE,
    DEFAULT_MAX_CHILDREN,
    DEFAULT_MAX_DOGS,
    DEFAULT_MAX_INCOME,
    DEFAULT_MIN_ADULT_AGE,
    DEFAULT_MIN_CHILDREN,
    DEFAULT_MIN_INCOME,
    EmploymentRequirement,
)
from app.schemas.base import BridgeModel, ResponseModel


def effective_reasoning_effort(model_id: str, effort: ReasoningEffort) -> ReasoningEffort | None:
    """Return the configured effort only when the selected model supports it.

    Keeping the inactive value in settings lets a pass switch providers without losing
    its choice, while excluding it from invocation and cache identity for Claude.
    """
    return effort if supports_reasoning_effort(model_id) else None


class AISettings(BridgeModel):
    """Admin-only AI provider configuration.

    A provider-native model ID identifies both the model and its route. The exact
    supported combinations live in ``model_catalog``; defaults remain on Bedrock so
    adding direct-provider credentials cannot change a deployed workload by itself.

    One model per AI pass, named by the JOB rather than a tier ("first pass" /
    "synthesis"), so each pass can be tuned independently and the mapping is
    self-documenting. The high-volume per-applicant passes (screening and dimension
    scoring) default to cheap-and-fast Haiku because call count drives their cost (scoring
    alone is candidates × dimensions). The higher-judgment discovery, decomposition,
    matching, and consolidation passes default to Sonnet. Evaluated direct Luna and Terra
    routes are available in production; moving a pass remains an explicit admin decision.

    ``match_model`` earned its own tier from evidence: on Haiku the identity-match
    pass over-matched genuinely-drifted concepts (freezing the wrong prior
    definition onto a reused score, carrying tier intent onto the wrong axis), so it
    runs on the stronger Sonnet tier rather than the high-volume Haiku tier. Any pass can
    move if representative evals and production availability justify the change.

    ``decompose_model`` (settles the K fan-out reports into one set) gets its own field
    for consistency and independent tunability — every pass has one. It's a genuinely
    different task (reasoning over K reports vs. reading the pool), so being able to move it
    without dragging discovery along is worth the one knob.

    ``consolidate_model`` (the post-score duplicate-merge confirm) defaults to Sonnet: it's
    the same high-stakes identity judgment as matching (a wrong merge is unrecoverable), so
    it wants the stronger model, not cheap Haiku.
    """

    region: str = Field(default="us-east-1")
    _HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    _SONNET = "us.anthropic.claude-sonnet-4-6"
    screening_model: str = Field(default=_HAIKU)
    screening_reasoning_effort: ReasoningEffort = "low"
    dimension_scoring_model: str = Field(default=_HAIKU)
    dimension_scoring_reasoning_effort: ReasoningEffort = "low"
    discovery_model: str = Field(default=_SONNET)
    discovery_reasoning_effort: ReasoningEffort = "low"
    decompose_model: str = Field(default=_SONNET)
    decompose_reasoning_effort: ReasoningEffort = "low"
    match_model: str = Field(default=_SONNET)
    match_reasoning_effort: ReasoningEffort = "low"
    consolidate_model: str = Field(default=_SONNET)
    consolidate_reasoning_effort: ReasoningEffort = "low"
    # Fan-Out Redesign (SPEC "Fan-Out Redesign", D6): how many parallel, fresh-context
    # discovery calls one Rank runs. Their cross-call variation is the diversity a later
    # decomposition step pares to the finest non-overlapping set. Discovery is uncached,
    # so K carries a real linear cost (see the cost model note); kept small and fixed,
    # not adaptive. K=1 degenerates to the single-discovery behaviour. Default 5: the 5th
    # fresh context is worth its modest cost for coverage (see the marginal-coverage note).
    discovery_fan_out: int = Field(default=5, ge=1, le=10)
    # Post-score consolidation (SPEC "Post-score consolidation"): the Pearson r at/above
    # which two dimensions' score vectors nominate the pair as a suspected duplicate for
    # the LLM confirm. Default 0.8 catches subtler forks; lowering further nominates more
    # pairs and hands the
    # merge-biased confirm more confounds to reject), raising nominates fewer. Tunable
    # because the right cut depends on the pool. Unbounded on purpose: an out-of-range
    # value is harmless (above 1 nominates nothing, below 0 everything), not an error, so
    # there's nothing to guard. Confirm still gates every merge, so this only moves what
    # gets *considered*, never auto-merges.
    consolidate_correlation_threshold: float = Field(default=0.8)
    spending_cap_usd: float = Field(default=2.0, ge=0)
    # How many applications to process concurrently. Provider quotas vary by account,
    # so this is an operator control as well as a latency control. StrandsProvider sizes
    # the Bedrock connection pool to match; direct SDK clients manage their own pools.
    max_workers: int = Field(default=50, ge=1, le=100)

    @field_validator(
        "screening_model",
        "dimension_scoring_model",
        "discovery_model",
        "decompose_model",
        "match_model",
        "consolidate_model",
    )
    @classmethod
    def supported_model(cls, value: str) -> str:
        model_spec(value)
        return value

    def selected_models(self) -> tuple[str, ...]:
        from app.ai.pass_catalog import AI_PASS_CATALOG

        return tuple(getattr(self, spec.model_attr) for spec in AI_PASS_CATALOG)


class EligibilityRules(BridgeModel):
    """The deterministic hard-filter thresholds and disabled checks for one member.

    Each member screens against their own thresholds; a member who hasn't diverged reads the
    shared committee default. Every rule here is pure math evaluated on read via
    ``evaluate_hard_filters`` — the numeric thresholds over ``normalized`` fields, plus the
    pet limits over the pet facts the screening pass extracts. They live here, separate from the
    shared infra config in ``AppSettings``.
    """

    income_min: int = Field(default=DEFAULT_MIN_INCOME, ge=0)
    income_max: int = Field(default=DEFAULT_MAX_INCOME, ge=0)
    min_adult_age: int = Field(default=DEFAULT_MIN_ADULT_AGE, ge=1, le=100)
    max_child_age: int = Field(default=DEFAULT_MAX_CHILD_AGE, ge=0, le=100)
    min_children: int = Field(default=DEFAULT_MIN_CHILDREN, ge=0, le=20)
    max_children: int = Field(default=DEFAULT_MAX_CHILDREN, ge=0, le=20)
    max_dogs: int = Field(default=DEFAULT_MAX_DOGS, ge=0, le=10)
    max_cats: int = Field(default=DEFAULT_MAX_CATS, ge=0, le=10)
    allow_other_pets: bool = Field(default=DEFAULT_ALLOW_OTHER_PETS)
    employment_requirement: EmploymentRequirement = EmploymentRequirement.NONE
    # One flat list spans both kinds of eligibility check: deterministic hard-filter reason
    # codes (income_below_range, pets_over_limit, …) AND AI screening flag categories
    # (fake_contact, internal_inconsistency, …). The two namespaces are disjoint; the hard
    # filter drops matching reason codes and the flag filter drops matching categories, each
    # ignoring the other's strings. Wire key: disabledChecks.
    disabled_checks: list[str] = Field(default_factory=list)


class AppSettings(BridgeModel):
    """Shared AI settings. Eligibility policy is stored separately."""

    ai: AISettings = Field(default_factory=AISettings)


class AIModelOption(ResponseModel):
    model_id: str
    label: str
    provider: ModelProvider
    supports_reasoning_effort: bool
    configured: bool


class AIPassOption(ResponseModel):
    key: str
    label: str
    model_setting: str
    reasoning_setting: str


class SettingsResponse(ResponseModel):
    settings: AppSettings
    ai_model_options: list[AIModelOption]
    ai_passes: list[AIPassOption]


class EligibilityRulesResponse(ResponseModel):
    """GET /eligibility-rules — the signed-in member's effective rules + whether they are the
    shared committee default (no personal divergence yet) or the member's own."""

    rules: EligibilityRules
    is_default: bool


class EligibilityCheck(ResponseModel):
    id: str
    label: str
    description: str


class EligibilityCheckCatalog(ResponseModel):
    deterministic: list[EligibilityCheck]
    ai: list[EligibilityCheck]
