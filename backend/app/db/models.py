from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class UserRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class ApplicationStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class StatusSource(StrEnum):
    UNTOUCHED = "untouched"  # passed rules, AI didn't flag (or hasn't run)
    RULES = "rules"  # deterministic filters set it ineligible (high trust)
    AI = "ai"  # AI quality pass set it ineligible (low trust — needs review)
    HUMAN = "human"  # a person set the status, either direction


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_class]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_subject: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(1000))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=enum_values),
        default=UserRole.MEMBER,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class GoogleCredential(TimestampMixin, Base):
    __tablename__ = "google_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    token: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    user: Mapped[User] = relationship()


class AdminSetting(TimestampMixin, Base):
    __tablename__ = "admin_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class Application(TimestampMixin, Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    primary_email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    applicant_name: Mapped[str | None] = mapped_column(String(255))
    co_applicant_name: Mapped[str | None] = mapped_column(String(255))
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, values_callable=enum_values),
        default=ApplicationStatus.ELIGIBLE,
        nullable=False,
        index=True,
    )
    status_source: Mapped[StatusSource] = mapped_column(
        Enum(StatusSource, values_callable=enum_values),
        default=StatusSource.UNTOUCHED,
        nullable=False,
        index=True,
    )
    # Immutable record of why the deterministic rules excluded the applicant.
    hard_filter_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # Hash of the machine findings (reasons + AI flags) captured when a human
    # last set the status. Null unless status_source == human. Used to detect
    # staleness: if the current findings hash differs, there are new findings
    # since the human's review.
    reviewed_fingerprint: Mapped[str | None] = mapped_column(String(64))


class ApplicationAIResult(TimestampMixin, Base):
    """Cached AI analysis for one application and analysis kind.

    ``cache_key`` is a hash of the application content + model + prompt version,
    so re-running an unchanged application with the same model/prompt reuses the
    stored result instead of paying for another call. ``output`` holds the
    validated structured-output JSON; usage/cost are kept for auditability.
    """

    __tablename__ = "application_ai_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    # The prompt version this result was produced under. Hashed into cache_key for
    # cache hits, but also stored plainly so cost estimates can prefer usage from
    # the current prompt version and fall back to earlier ones. Nullable: rows
    # written before this column have an unknown version.
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # The model's free-text reasoning alongside the structured output, kept for the
    # admin "Raw AI output" view. Nullable: not every provider surfaces it.
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    application: Mapped[Application] = relationship()


class SyncRun(TimestampMixin, Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_sheet_id: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    eligible_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filtered_out_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Hash of the import-relevant settings (sheet id + hard-filter thresholds +
    # disabled rules) at import time. Lets the dashboard flag Import as out of
    # date when settings change after a sync — a re-import would reclassify
    # eligibility. Null on rows imported before this column existed.
    settings_fingerprint: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)


class ScreeningRun(TimestampMixin, Base):
    __tablename__ = "screening_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    source_sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_runs.id"))
    criteria: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(80), default="draft", nullable=False)

    owner: Mapped[User | None] = relationship()
    source_sync_run: Mapped[SyncRun | None] = relationship()
