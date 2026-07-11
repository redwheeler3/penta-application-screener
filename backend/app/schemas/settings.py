import re

from pydantic import Field, field_validator

# Threshold defaults are owned by the domain layer (the single source of truth);
# the settings schema references them so a default can't drift between the two.
from app.domain.hard_filters import (
    DEFAULT_MAX_CHILD_AGE,
    DEFAULT_MAX_CHILDREN,
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
    self-documenting. Today the high-volume per-applicant passes (screening, essay
    analysis, dimension scoring) default to cheap-and-fast Haiku because call COUNT
    is what drives their cost (scoring alone is candidates × dimensions), while the
    two once-per-rank pool-level passes (discovery, matching) default to the
    stronger Sonnet — cost is trivial there and judgment quality matters.

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
    is worth the one knob. (The former ``reconcile_model`` was removed with the reconcile
    pass in the fan-out redesign.)
    """

    region: str = Field(default="us-west-2")
    _HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    _SONNET = "us.anthropic.claude-sonnet-4-6"
    screening_model: str = Field(default=_HAIKU)
    essay_analysis_model: str = Field(default=_HAIKU)
    dimension_scoring_model: str = Field(default=_HAIKU)
    discovery_model: str = Field(default=_SONNET)
    decompose_model: str = Field(default=_SONNET)
    match_model: str = Field(default=_SONNET)
    # Fan-Out Redesign (SPEC "Fan-Out Redesign", D6): how many parallel, fresh-context
    # discovery calls one Rank runs. Their cross-call variation is the diversity a later
    # decomposition step pares to the finest non-overlapping set. Discovery is uncached,
    # so K carries a real linear cost (see the cost model note); kept small and fixed,
    # not adaptive. K=1 degenerates to the single-discovery behaviour. Default 5 (D6
    # first reasoned to 4 on cost; raised to 5 on 2026-07-10 — the extra fresh context
    # is worth the modest cost for coverage).
    discovery_fan_out: int = Field(default=5, ge=1, le=10)
    spending_cap_usd: float = Field(default=1.0, ge=0)
    # How many applications to screen concurrently. The model calls are the slow,
    # blocking part; ~300 applicants finish in seconds at this width. The Bedrock
    # connection pool is sized to match (see StrandsProvider), so don't raise one
    # without the other. Bedrock quotas (10k RPM / 5M TPM) are far above this.
    max_workers: int = Field(default=50, ge=1, le=100)


class AppSettings(BridgeModel):
    google_sheet_id: str = Field(default="", max_length=2000)
    income_min: int = Field(default=DEFAULT_MIN_INCOME, ge=0)
    income_max: int = Field(default=DEFAULT_MAX_INCOME, ge=0)
    min_adult_age: int = Field(default=DEFAULT_MIN_ADULT_AGE, ge=1, le=100)
    max_child_age: int = Field(default=DEFAULT_MAX_CHILD_AGE, ge=0, le=100)
    min_children: int = Field(default=DEFAULT_MIN_CHILDREN, ge=0, le=20)
    max_children: int = Field(default=DEFAULT_MAX_CHILDREN, ge=0, le=20)
    max_dogs: int = Field(default=1, ge=0, le=10)
    max_cats: int = Field(default=1, ge=0, le=10)
    allow_other_pets: bool = False
    disabled_rules: list[str] = Field(default_factory=list)
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


class SettingsResponse(ResponseModel):
    settings: AppSettings
    google_sheet_url: str = ""
    google_sheet_title: str | None = None
