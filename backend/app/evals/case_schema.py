"""Golden-file contracts shared by the editor and the live/judge readers.

Validate the stored envelope without rewriting it: notes and extra captured input remain
intact, while a missing or wrongly typed consumer field cannot corrupt the versioned corpus.
"""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.ai.schemas import FlagCategory


class CaseValidationError(ValueError):
    """A golden case cannot be consumed by its eval family."""


class _StoredModel(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class _Descriptor(_StoredModel):
    key: str
    definition: str
    name: str = ""
    high_end: str = ""
    low_end: str = ""


class _NamedDescriptor(_Descriptor):
    name: str


class _ScoringDimension(_NamedDescriptor):
    high_end: str
    low_end: str


class _ScoringGiven(_StoredModel):
    applicant: dict[str, object]
    dimension: _ScoringDimension


class _ScoringExpected(_StoredModel):
    score_min: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)] | None = None
    score_max: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)] | None = None
    confidence: str | None = None

    @model_validator(mode="after")
    def check_band(self):
        if not self.model_fields_set & {"score_min", "score_max", "confidence"}:
            raise ValueError("expected needs a score bound or confidence")
        for name in self.model_fields_set & {"score_min", "score_max", "confidence"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if self.score_min is not None and self.score_max is not None and self.score_min > self.score_max:
            raise ValueError("score_min must not exceed score_max")
        if self.confidence is not None:
            if not {part.strip() for part in self.confidence.split("|")} <= {"low", "medium", "high"}:
                raise ValueError("confidence must be low, medium, high, or a pipe-separated choice")
        return self


class _MatchingGiven(_StoredModel):
    prior: Annotated[list[_NamedDescriptor], Field(min_length=1)]
    new: Annotated[list[_NamedDescriptor], Field(min_length=1)]


class _DecompositionGiven(_StoredModel):
    reports: list[list[_Descriptor]]


class _ConsolidationGiven(_StoredModel):
    pair: Annotated[list[_NamedDescriptor], Field(min_length=2, max_length=2)]


class _ScreeningGiven(_StoredModel):
    fields: dict[str, object]
    essays: dict[str, object]


def normalize_flag_category(value: str) -> str:
    """Trim fixture input and reject names the production output cannot produce."""
    category = value.strip()
    if category not in {item.value for item in FlagCategory}:
        raise ValueError(f"unknown screening flag category: {value!r}")
    return category


def normalize_fires(fires: list[str | list[str]] | str) -> list[str | list[str]]:
    """Each entry requires one category or any one category in a list/pipe group."""
    entries = [fires] if isinstance(fires, str) else fires
    normalized = []
    for entry in entries:
        group = entry.split("|") if isinstance(entry, str) else entry
        if not group:
            raise ValueError("an any-of flag group needs at least one category")
        categories = [normalize_flag_category(item) for item in group]
        normalized.append(categories[0] if isinstance(entry, str) and len(categories) == 1 else categories)
    return normalized


class _PetExpected(_StoredModel):
    dogs: Annotated[int, Field(ge=0)] = 0
    cats: Annotated[int, Field(ge=0)] = 0
    other_pets: list[str] = []


class _ScreeningExpected(_StoredModel):
    fires: list[str | list[str]] | str = []
    absent: list[str] = []
    pets: _PetExpected | None = None

    @model_validator(mode="before")
    @classmethod
    def common_contested_policy(cls, value):
        if isinstance(value, dict) and "contested" in value:
            raise ValueError("put contested in metadata, alongside expected")
        return value

    @field_validator("fires")
    @classmethod
    def valid_required_flags(cls, value):
        normalize_fires(value)
        return value

    @field_validator("absent")
    @classmethod
    def valid_forbidden_flags(cls, value):
        for category in value:
            normalize_flag_category(category)
        return value


class _Metadata[Expected](_StoredModel):
    expected: Expected
    note: str = ""
    contested: bool = False
    label_rationale: str = ""


class _Case[Given, Expected](_StoredModel):
    key: Annotated[str, Field(min_length=1, pattern=r"\S")]
    metadata: _Metadata[Expected]
    given: Given


_SCHEMAS = {
    "scoring": _Case[_ScoringGiven, _ScoringExpected],
    "matching": _Case[_MatchingGiven, Literal["matches", "mismatches"]],
    "decomposition": _Case[_DecompositionGiven, Literal["merge", "keep"]],
    "consolidation": _Case[_ConsolidationGiven, Literal["merge", "keep"]],
    "screening": _Case[_ScreeningGiven, _ScreeningExpected],
}


def validate_case(eval_key: str, case: dict) -> None:
    """Reject malformed inputs before either publication or reader flattening."""
    metadata = case.get("metadata")
    if isinstance(metadata, dict) and "pass" in metadata and metadata["pass"] != eval_key:
        raise CaseValidationError(f"metadata.pass must match owning family {eval_key!r}")
    try:
        _SCHEMAS[eval_key].model_validate(case)
    except ValidationError as exc:
        errors = [f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                  for error in exc.errors(include_input=False, include_url=False)]
        raise CaseValidationError("; ".join(errors)) from exc
