from datetime import date
import re

from pydantic import BaseModel, Field, field_validator


SHEETS_URL_ID_PATTERN = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
SHEETS_OPEN_ID_PATTERN = re.compile(r"[?&]id=([a-zA-Z0-9-_]+)")


def google_sheet_url_from_id(sheet_id: str) -> str:
    if not sheet_id:
        return ""
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


class AISettings(BaseModel):
    """Admin-only AI provider configuration.

    Model IDs are Bedrock inference profile IDs (the ``us.`` / ``global.``
    prefixed form), not bare on-demand model IDs, which Bedrock requires for
    these models. The quality-flag pass uses the cheaper first-pass model;
    judgment-heavier milestones will use the synthesis model.
    """

    region: str = Field(default="us-west-2")
    first_pass_model: str = Field(default="us.anthropic.claude-haiku-4-5-20251001-v1:0")
    synthesis_model: str = Field(default="us.anthropic.claude-sonnet-4-6")
    spending_cap_usd: float = Field(default=0.5, ge=0)


class AppSettings(BaseModel):
    google_sheet_id: str = Field(default="", max_length=2000)
    unit_size: str = Field(default="2br", pattern="^(1br|2br|3br)$")
    move_in_date: date = date(2026, 9, 1)
    income_min: int = Field(default=70_000, ge=0)
    income_max: int = Field(default=150_000, ge=0)
    max_adults: int = Field(default=2, ge=1, le=10)
    min_adult_age: int = Field(default=19, ge=1, le=100)
    max_dogs: int = Field(default=1, ge=0, le=10)
    max_cats: int = Field(default=1, ge=0, le=10)
    allow_other_pets: bool = False
    income_mismatch_tolerance: int = Field(default=1_000, ge=0)
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


class SettingsResponse(BaseModel):
    settings: AppSettings
    google_sheet_url: str = ""
    google_sheet_title: str | None = None
