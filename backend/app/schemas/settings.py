import re

from pydantic import Field, field_validator

from app.schemas.base import BridgeModel, ResponseModel

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
    these models. The screening pass uses the cheaper first-pass model;
    judgment-heavier milestones will use the synthesis model.
    """

    region: str = Field(default="us-west-2")
    first_pass_model: str = Field(default="us.anthropic.claude-haiku-4-5-20251001-v1:0")
    synthesis_model: str = Field(default="us.anthropic.claude-sonnet-4-6")
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
