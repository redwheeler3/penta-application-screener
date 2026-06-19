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


class HardFilterStatus(StrEnum):
    ELIGIBLE = "eligible"
    FILTERED_OUT = "filtered_out"


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
    hard_filter_status: Mapped[HardFilterStatus] = mapped_column(
        Enum(HardFilterStatus, values_callable=enum_values),
        default=HardFilterStatus.ELIGIBLE,
        nullable=False,
        index=True,
    )
    hard_filter_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)


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
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
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
    eligible_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filtered_out_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
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
