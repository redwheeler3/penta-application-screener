import re

from pydantic import Field, field_validator

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
)
from app.schemas.base import BridgeModel, ResponseModel

SHEETS_URL_ID_PATTERN = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
SHEETS_OPEN_ID_PATTERN = re.compile(r"[?&]id=([a-zA-Z0-9-_]+)")


def google_sheet_url_from_id(sheet_id: str) -> str:
    if not sheet_id:
        return ""
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


class AISettings(BridgeModel):
    """Admin-only AI provider configuration.

    Model IDs are Bedrock inference profile IDs (the ``us.`` / ``global.``
    prefixed form), not bare on-demand model IDs, which Bedrock requires for
    these models.

    One model per AI pass, named by the JOB rather than a tier ("first pass" /
    "synthesis"), so each pass can be tuned independently and the mapping is
    self-documenting. Today the high-volume per-applicant passes (screening, dimension
    scoring) default to cheap-and-fast Haiku because call COUNT is what drives their cost
    (scoring alone is candidates × dimensions), while the once-per-rank pool-level passes
    (discovery, matching) default to the stronger Sonnet — cost is trivial there and
    judgment quality matters.

    ``match_model`` earned its own tier from evidence: on Haiku the identity-match
    pass over-matched genuinely-drifted concepts (freezing the wrong prior
    definition onto a reused score, carrying tier intent onto the wrong axis), so it
    runs on the model already trusted for the HARDER discovery task. Any of these
    can move to Opus if a real run shows the current default is too weak for the job.

    ``decompose_model`` (settles the K fan-out reports into one set) gets its own field
    for consistency and independent tunability — every pass has one — even though it
    defaults to the same synthesis tier as discovery. It's a genuinely different task
    (reasoning over K reports vs. reading the pool), so being able to move it — e.g. to
    Opus if settling proves harder than discovering — without dragging discovery along
    is worth the one knob.

    ``consolidate_model`` (the post-score duplicate-merge confirm) defaults to the
    synthesis tier: it's the same high-stakes identity judgment as matching (a wrong
    merge is unrecoverable), so it wants the stronger model, not cheap Haiku.
    """

    region: str = Field(default="us-west-2")
    _HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    _SONNET = "us.anthropic.claude-sonnet-4-6"
    screening_model: str = Field(default=_HAIKU)
    dimension_scoring_model: str = Field(default=_HAIKU)
    discovery_model: str = Field(default=_SONNET)
    decompose_model: str = Field(default=_SONNET)
    match_model: str = Field(default=_SONNET)
    consolidate_model: str = Field(default=_SONNET)
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
    # How many applications to screen concurrently. The model calls are the slow,
    # blocking part; ~300 applicants finish in seconds at this width. The Bedrock
    # connection pool is sized to match (see StrandsProvider), so don't raise one
    # without the other. Bedrock quotas (10k RPM / 5M TPM) are far above this.
    max_workers: int = Field(default=50, ge=1, le=100)


class EligibilityRules(BridgeModel):
    """The deterministic hard-filter thresholds — per-member as of M15 1d, including pet
    limits as of 1e.

    Each member screens against their own thresholds; a member who hasn't diverged reads the
    shared committee default. Every rule here is pure math evaluated on read via
    ``evaluate_hard_filters`` — the numeric thresholds over ``normalized`` fields, plus the
    pet limits over the pet facts the screening pass extracts (1e moved pets out of the
    shared screening prompt into this per-member filter). So they live here, separate from the
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
    # The checks this member has switched off (1g Move 3, renamed from disabled_rules). ONE
    # flat list spanning BOTH kinds of eligibility check: deterministic hard-filter reason
    # codes (income_below_range, pets_over_limit, …) AND AI screening flag categories
    # (fake_contact, internal_inconsistency, …). The two namespaces are disjoint; the hard
    # filter drops matching reason codes and the flag filter drops matching categories, each
    # ignoring the other's strings. Wire key: disabledChecks.
    disabled_checks: list[str] = Field(default_factory=list)


class AppSettings(BridgeModel):
    """Shared, committee-wide infra config: the source sheet and AI provider settings. The
    per-member eligibility thresholds — including pet limits as of M15 1e — live in
    ``EligibilityRules``, not here."""

    google_sheet_id: str = Field(default="", max_length=2000)
    # The user whose stored Google token reads the sheet during sync — the admin who linked
    # it via the Picker (M18). Sync uses THIS token regardless of who clicks Sync, so members
    # never need a Drive/Sheets scope. None until an admin links a sheet (falls back to the
    # syncing user's own token — the pre-M18 behaviour — so nothing breaks in the interim).
    google_sheet_reader_user_id: int | None = Field(default=None)
    ai: AISettings = Field(default_factory=AISettings)

    @field_validator("google_sheet_id")
    @classmethod
    def normalize_google_sheet_id(cls, value: str) -> str:
        spreadsheet_reference = value.strip()
        if not spreadsheet_reference:
            return ""

        for pattern in (SHEETS_URL_ID_PATTERN, SHEETS_OPEN_ID_PATTERN):
            match = pattern.search(spreadsheet_reference)
            if match:
                return match.group(1)

        return spreadsheet_reference


class SheetCodeExchangeRequest(BridgeModel):
    """The GIS code-model authorization code from the admin's one-click grant (M18), POSTed so
    the backend can exchange it for a refresh+access token."""

    code: str = Field(min_length=1)


class SheetLinkRequest(BridgeModel):
    """Admin links the applications sheet via the Google Picker (M18). The Picker only PICKS the
    file (returns its id); the sheet is READ during sync with the linking admin's own stored
    LOGIN token — which carries drive.file + a refresh_token (offline access), so it reads
    durably and auto-refreshes. Hence only the file id is sent here, not the Picker's
    short-lived (non-refreshable) access token. The endpoint marks the admin the designated
    reader, so members need no Drive/Sheets scope at all.

    Precondition: the linking admin must have signed in with the reader scopes (drive.file),
    i.e. their stored token can access files they've picked. The endpoint verifies this by
    reading the sheet's title before saving, and 409s with a re-connect prompt otherwise."""

    file_id: str = Field(min_length=1, max_length=2000)


class SettingsResponse(ResponseModel):
    settings: AppSettings
    google_sheet_url: str = ""
    google_sheet_title: str | None = None


class EligibilityRulesResponse(ResponseModel):
    """GET /eligibility-rules — the signed-in member's effective rules + whether they are the
    shared committee default (no personal divergence yet) or the member's own."""

    rules: EligibilityRules
    is_default: bool
