from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
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


class OpeningPhase(StrEnum):
    UPCOMING = "upcoming"
    OPEN = "open"
    CLOSED = "closed"
    ARCHIVED = "archived"


class OpeningIntakeMode(StrEnum):
    APPLICATIONS = "applications"
    DIRECT_SELECTION = "direct_selection"


class OpeningOutcome(StrEnum):
    SELECTED = "selected"
    UNSUCCESSFUL = "unsuccessful"


class StatusSource(StrEnum):
    UNTOUCHED = "untouched"  # passed rules, AI didn't flag (or hasn't run)
    RULES = "rules"  # deterministic filters set it ineligible (high trust)
    AI = "ai"  # AI screening pass set it ineligible (low trust — needs review)
    HUMAN = "human"  # a person set the status, either direction


class PasswordlessIdentityKind(StrEnum):
    APPLICANT = "applicant"
    COMMITTEE = "committee"


class MagicLinkPurpose(StrEnum):
    APPLICANT_ACCESS = "applicant_access"
    COMMITTEE_ACCESS = "committee_access"
    EMAIL_CHANGE = "email_change"


class ApplicantDraftIntent(StrEnum):
    SAVE = "save"
    SUBMIT = "submit"


class EmailDeliveryState(StrEnum):
    QUEUED = "queued"
    ACCEPTED = "accepted"
    FAILED = "failed"


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
    # Activity is deliberately two timestamps, not an event log. It excludes pages,
    # IP addresses, and devices.
    first_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeniedSignInAttempt(Base):
    """A Google identity rejected by the committee access boundary.

    The row retains only identity and time needed for access administration. It
    deliberately excludes OAuth tokens, IP addresses, devices, and page activity.
    """

    __tablename__ = "denied_sign_in_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_subject: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AccessAllowlistEntry(TimestampMixin, Base):
    """One approved committee email identity and the role it is admitted with.

    Google and email-link sign-ins are admitted only when the verified email matches
    an entry here. The resulting ``User`` takes the entry's role, so this table also
    owns role management. Initial admins are seeded from a config file at startup;
    after that admins manage the list in-app.
    """

    __tablename__ = "access_allowlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=enum_values),
        default=UserRole.MEMBER,
        nullable=False,
    )


class RunLock(TimestampMixin, Base):
    """A single-row advisory lease serializing expensive AI runs across members.

    Screen / full Rank / score-current all write shared state; two overlapping runs waste
    spend and — for a full Rank — strand a MemberRanking (last-writer-wins on the current
    ``Analysis``). There is no in-process lock that would survive multiple web workers, so the
    serialization lives in the DB: one fixed row (``id=1``, seeded by migration), claimed by an
    atomic conditional UPDATE and released in the run stream's ``finally``. ``held_since`` backs
    a TTL steal so a crashed run can't wedge the system forever. A Postgres deployment can
    use the same lease or replace it with a native advisory lock."""

    __tablename__ = "run_lock"

    id: Mapped[int] = mapped_column(primary_key=True)  # always 1 — the single lease row
    # Who holds the lease and what they're running; NULL when free.
    holder_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str | None] = mapped_column(String(20))  # screen | rank | rank_scores
    # When the current holder claimed it — the TTL-steal reference (a lease older than the TTL
    # is presumed dead and reclaimable). NULL when free.
    held_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Feedback(TimestampMixin, Base):
    """A member's free-text feedback, captured from any page and surfaced to admins.
    The point is to let an admin act on real member
    friction without a back-and-forth, so each row carries the context the member had
    when they hit it — the route/tab they were on and the ranking they were viewing —
    stamped server-side alongside identity, app version, and time so it can't be omitted.

    Treated as SENSITIVE: a member may paste applicant specifics into the free text, so
    reads are admin-only, it never feeds AI, and it's never logged or exported.
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Where the member was when they submitted — the client sends both; either may be
    # blank (feedback from a page with no active tab/route). Context, not identity.
    route: Mapped[str | None] = mapped_column(String(500))
    active_tab: Mapped[str | None] = mapped_column(String(100))
    # The ranking they were viewing, if any — nullable (feedback before any Rank runs).
    # No FK: an analysis can be superseded, and we want the id preserved for context even
    # if that row is later gone, rather than blocking the delete or nulling on cascade.
    analysis_id: Mapped[int | None] = mapped_column()
    # The applicant whose detail page they were on, if any — nullable (most feedback is
    # from a list/ranking, not a drill-in). No FK, same reasoning as analysis_id: keep the
    # id for context even if the applicant is later removed; the admin view resolves the
    # current name on read (blank if gone).
    applicant_id: Mapped[int | None] = mapped_column()
    # The build the feedback came from, stamped server-side (see app.version).
    app_version: Mapped[str] = mapped_column(String(50), nullable=False)
    # Set when an admin marks the item handled; null = still open. Resolved items are
    # retained (hidden by default) so the friction history survives for later mining.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class AdminSetting(TimestampMixin, Base):
    __tablename__ = "admin_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DailyMaintenanceRun(TimestampMixin, Base):
    """One durable lease for one maintenance task on one Pacific calendar day."""

    __tablename__ = "daily_maintenance_runs"
    __table_args__ = (UniqueConstraint("task", "pacific_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    pacific_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(120))


class RetentionDeletion(Base):
    """Non-identifying proof that one aggregate was removed under a retention rule."""

    __tablename__ = "retention_deletions"
    __table_args__ = (UniqueConstraint("record_kind", "record_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    record_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_rule: Mapped[str] = mapped_column(String(50), nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Application(TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index(
            "uq_applications_active_primary_email",
            "primary_email",
            unique=True,
            sqlite_where=text("withdrawn_at IS NULL"),
            postgresql_where=text("withdrawn_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    primary_email: Mapped[str] = mapped_column(String(320), nullable=False)
    applicant_name: Mapped[str | None] = mapped_column(String(255))
    co_applicant_name: Mapped[str | None] = mapped_column(String(255))
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Private applicant edits. The submitted projection above remains unchanged until an
    # explicit publication replaces it, so committee reads and AI caches cannot see drafts.
    working_answers: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    working_opening_ids: Mapped[list[int] | None] = mapped_column(JSON)
    working_content_hash: Mapped[str | None] = mapped_column(String(64))
    working_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    working_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Null means a never-submitted draft. Retained externally collected rows are
    # submitted; built-in drafts start null.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    retention_due_on: Mapped[date | None] = mapped_column(Date)
    # Provenance for evidence-bearing eval exports. Production form submissions are
    # false; committed synthetic fixtures and explicitly synthetic local intake are true.
    synthetic_data: Mapped[bool] = mapped_column(
        default=False, server_default="0", nullable=False
    )
    # Eligibility is derived on read per member: deterministic reasons come from
    # ``evaluate_hard_filters`` over ``normalized`` and the member's rules; AI findings from cached
    # screening flags; a member's human override from ``MemberEligibility``. Intake stores no
    # verdict. See ``services/eligibility`` + ``services/rules``.


class Opening(TimestampMixin, Base):
    """One available unit, opened for applications or filled from a prior pool.

    Location is intentionally absent: the public Penta site describes the neighbourhood,
    while an opening carries only details specific to the available unit.
    """

    __tablename__ = "openings"
    __table_args__ = (
        CheckConstraint("unit_size_bedrooms BETWEEN 1 AND 3", name="ck_opening_unit_size"),
        CheckConstraint("housing_charge_cents >= 0", name="ck_opening_housing_charge"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    intake_mode: Mapped[OpeningIntakeMode] = mapped_column(
        Enum(OpeningIntakeMode, values_callable=enum_values),
        default=OpeningIntakeMode.APPLICATIONS,
        server_default=OpeningIntakeMode.APPLICATIONS.value,
        nullable=False,
    )
    unit_size_bedrooms: Mapped[int] = mapped_column(Integer, nullable=False)
    housing_charge_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    application_open_date: Mapped[date | None] = mapped_column(Date)
    application_close_date: Mapped[date | None] = mapped_column(Date)
    move_in_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Application-intake openings are published immediately. Pacific calendar dates determine
    # their phase; direct selections stay closed until their move-in date archives them.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    no_household_selected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    no_household_selected_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id")
    )


class VacancySubscription(TimestampMixin, Base):
    """One active request for a single future vacancy notification."""

    __tablename__ = "vacancy_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "wants_one_bedroom OR wants_two_bedroom OR wants_three_bedroom",
            name="ck_vacancy_subscription_has_unit_size",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    wants_one_bedroom: Mapped[bool] = mapped_column(Boolean, nullable=False)
    wants_two_bedroom: Mapped[bool] = mapped_column(Boolean, nullable=False)
    wants_three_bedroom: Mapped[bool] = mapped_column(Boolean, nullable=False)
    first_consented_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    consent_version: Mapped[str | None] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    managed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)

    managed_by: Mapped[User | None] = relationship()


class VacancyConsentReceipt(Base):
    """Minimal evidence for the consent used to send one vacancy notice."""

    __tablename__ = "vacancy_consent_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(Integer, nullable=False)
    email_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    unit_sizes: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consent_version: Mapped[str | None] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    fulfilled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retain_until: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    email_delivery_id: Mapped[int] = mapped_column(Integer, nullable=False)


class VacancySubscriptionAudit(Base):
    """PII-minimized audit of manual vacancy-list changes."""

    __tablename__ = "vacancy_subscription_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int | None] = mapped_column(index=True)
    email_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    acted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    acted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    acted_by: Mapped[User] = relationship()


class ApplicationParticipation(TimestampMixin, Base):
    """An applicant's explicit entry into one opening, separate from their durable answers."""

    __tablename__ = "application_participations"
    __table_args__ = (
        UniqueConstraint("application_id", "opening_id"),
        Index(
            "uq_participations_selected_application",
            "application_id",
            unique=True,
            sqlite_where=text("outcome = 'selected'"),
        ),
        Index(
            "uq_participations_selected_opening",
            "opening_id",
            unique=True,
            sqlite_where=text("outcome = 'selected'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    opening_id: Mapped[int] = mapped_column(ForeignKey("openings.id"), index=True, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[OpeningOutcome | None] = mapped_column(
        Enum(OpeningOutcome, values_callable=enum_values), index=True
    )
    outcome_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome_decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    unsuccessful_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    application: Mapped[Application] = relationship()
    opening: Mapped[Opening] = relationship()
    outcome_decided_by: Mapped[User | None] = relationship()


class ApplicationVersion(Base):
    """One immutable application publication, independent of opening participation."""

    __tablename__ = "application_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    normalized: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    selected_opening_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    terms_version: Mapped[str | None] = mapped_column(String(30))

    application: Mapped[Application] = relationship()


class ApplicantDraft(Base):
    """A private draft that has not yet been claimed through an applicant session."""

    __tablename__ = "applicant_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    intent: Mapped[ApplicantDraftIntent] = mapped_column(
        Enum(ApplicantDraftIntent, values_callable=enum_values), nullable=False
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    draft_token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    working_answers: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    working_opening_ids: Mapped[list[int] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_due_on: Mapped[date] = mapped_column(Date, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application | None] = relationship()


class MagicLinkToken(Base):
    """A short-lived, single-use emailed credential stored only as a hash."""

    __tablename__ = "magic_link_tokens"
    __table_args__ = (
        CheckConstraint(
            "(identity_kind = 'applicant' AND user_id IS NULL AND "
            "((application_id IS NOT NULL AND applicant_draft_id IS NULL) OR "
            "(application_id IS NULL AND applicant_draft_id IS NOT NULL))) "
            "OR (identity_kind = 'committee' AND user_id IS NOT NULL "
            "AND application_id IS NULL AND applicant_draft_id IS NULL)",
            name="ck_magic_link_token_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    identity_kind: Mapped[PasswordlessIdentityKind] = mapped_column(
        Enum(PasswordlessIdentityKind, values_callable=enum_values), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    applicant_draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("applicant_drafts.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    initiating_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("browser_sessions.id"), index=True
    )
    purpose: Mapped[MagicLinkPurpose] = mapped_column(
        Enum(MagicLinkPurpose, values_callable=enum_values), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    remember_device: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application | None] = relationship()
    applicant_draft: Mapped[ApplicantDraft | None] = relationship()
    user: Mapped[User | None] = relationship()


class BrowserSession(Base):
    """An applicant or committee browser session, revocable server-side."""

    __tablename__ = "browser_sessions"
    __table_args__ = (
        CheckConstraint(
            "(identity_kind = 'applicant' AND application_id IS NOT NULL AND user_id IS NULL) "
            "OR (identity_kind = 'committee' AND user_id IS NOT NULL AND application_id IS NULL)",
            name="ck_browser_session_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    identity_kind: Mapped[PasswordlessIdentityKind] = mapped_column(
        Enum(PasswordlessIdentityKind, values_callable=enum_values), nullable=False, index=True
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    reconciliation_draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("applicant_drafts.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application | None] = relationship()
    reconciliation_draft: Mapped[ApplicantDraft | None] = relationship()
    user: Mapped[User | None] = relationship()


class EmailDelivery(TimestampMixin, Base):
    """Provider delivery metadata plus a credential-safe retry intent.

    ``retry_intent`` describes how to rebuild a message but never stores a magic-link
    credential or rendered message body. It is cleared after acceptance or terminal failure.
    """

    __tablename__ = "email_deliveries"
    __table_args__ = (
        CheckConstraint(
            "(recipient_kind = 'applicant' AND user_id IS NULL AND "
            "((application_id IS NOT NULL AND applicant_draft_id IS NULL) OR "
            "(application_id IS NULL AND applicant_draft_id IS NOT NULL) OR "
            "(application_id IS NULL AND applicant_draft_id IS NULL))) "
            "OR (recipient_kind = 'committee' AND user_id IS NOT NULL "
            "AND application_id IS NULL AND applicant_draft_id IS NULL)",
            name="ck_email_delivery_recipient",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(120), unique=True, index=True
    )
    message_kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    recipient_kind: Mapped[PasswordlessIdentityKind] = mapped_column(
        Enum(PasswordlessIdentityKind, values_callable=enum_values), nullable=False, index=True
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    magic_link_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("magic_link_tokens.id", ondelete="CASCADE"), index=True
    )
    applicant_draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("applicant_drafts.id", ondelete="CASCADE"), index=True
    )
    # Retained for targetless queued or failed mail so administrators can identify the recipient.
    # Accepted mail clears it because SocketLabs owns delivery history after acceptance.
    recipient_email: Mapped[str | None] = mapped_column(String(320))
    state: Mapped[EmailDeliveryState] = mapped_column(
        Enum(EmailDeliveryState, values_callable=enum_values), nullable=False, index=True
    )
    retry_intent: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    quota_blocked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False, index=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(120))

    application: Mapped[Application | None] = relationship()
    user: Mapped[User | None] = relationship()
    magic_link_token: Mapped[MagicLinkToken | None] = relationship()
    applicant_draft: Mapped[ApplicantDraft | None] = relationship()


class MemberEligibility(TimestampMixin, Base):
    """One member's human override of an applicant's eligibility.

    Sparse by design: a row exists ONLY where a member has overridden the computed machine
    verdict — there is no per-member machine row, because the machine status is derived on read
    from the applicant's shared ``hard_filter_reasons`` + cached screening flags. Effective
    eligibility for (member, applicant) = this override if present, else the machine verdict.
    ``status_source`` is not stored: a row's existence IS the human override (source = human).
    """

    __tablename__ = "member_eligibility"
    __table_args__ = (UniqueConstraint("application_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, values_callable=enum_values), nullable=False
    )
    # Hash of the machine findings (reasons + AI flags) when this member set the override.
    # A differing current hash means new findings since their review — the override is stale.
    reviewed_fingerprint: Mapped[str | None] = mapped_column(String(64))

    application: Mapped[Application] = relationship()
    user: Mapped[User] = relationship()


class MemberRules(TimestampMixin, Base):
    """One member's diverged eligibility thresholds.

    Sparse copy-on-write: a row exists ONLY once a member customizes their rules away from the
    shared committee default (stored in ``AdminSetting`` under ``committee_default_rules``).
    Until then the member reads the default — most members never diverge, so most have no row.
    ``rules`` is the ``EligibilityRules`` blob: numeric thresholds (income/age/children), pet
    limits, and ``disabled_checks`` — the flat set of switched-off checks spanning both
    deterministic reason codes and AI flag categories.
    """

    __tablename__ = "member_rules"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True, nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    user: Mapped[User] = relationship()


class ApplicationNote(TimestampMixin, Base):
    """A reviewer's private note on one application.

    Notes are deliberately separate from the application and its AI results: they
    belong to one member, never enter model prompts, and are never shared by a
    general application response.
    """

    __tablename__ = "application_notes"
    __table_args__ = (UniqueConstraint("application_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    application: Mapped[Application] = relationship()
    user: Mapped[User] = relationship()


class ApplicationStar(TimestampMixin, Base):
    """A reviewer's private star (favourite) on one application.

    Like a note, a star belongs to one member and is never shared: it is a
    personal working aid — a bookmark plus a list filter — with no effect on
    ranking, eligibility, or reports. The row's existence IS the state (starred
    when present), so there is no boolean column; unstarring deletes the row.
    """

    __tablename__ = "application_stars"
    __table_args__ = (UniqueConstraint("application_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    application: Mapped[Application] = relationship()
    user: Mapped[User] = relationship()


class ApplicationAIResult(TimestampMixin, Base):
    """Cached AI analysis for one application and analysis kind.

    ``cache_key`` hashes application content + provider-neutral model identity +
    reasoning + prompt version, so an unchanged application reuses the stored result
    across equivalent routes. ``model_id`` retains the route that produced it.
    ``output`` holds the validated structured-output JSON; usage/cost are kept for
    auditability.
    """

    __tablename__ = "application_ai_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    # Effective invocation value, not merely the current setting. None means the model did
    # not use reasoning effort or the row predates provenance capture.
    reasoning_effort: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # The prompt version this result was produced under. Hashed into cache_key, but
    # also stored plainly so cost estimates can prefer current-version usage.
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # The model's free-text reasoning, for the admin "Raw AI output" view. Nullable:
    # not every provider surfaces it.
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    application: Mapped[Application] = relationship()


class RunCostLedger(TimestampMixin, Base):
    """One row per completed AI run (a Screen, full Rank, or score-current update) — the
    header. This is the authoritative source of *per-run* cost:
    ``ApplicationAIResult`` is a reuse cache with no
    run-id stamp, so a run's fresh vs. cached split can't be reconstructed after the fact —
    it must be recorded as the run completes. The per-pass breakdown (tokens, cost, cache)
    lives in child ``RunPassCost`` rows, one per pass, so a token/model breakdown is a
    first-class queryable column rather than buried in a JSON blob.

    ``kind`` is "screen", "rank", or "rank_scores".
    """

    __tablename__ = "run_cost_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # screen | rank | rank_scores
    # The pre-run cost projection (the number the confirmation card showed the committee),
    # captured so estimate-vs-actual drift is queryable. 0.0 means no estimate is available.
    estimated_usd: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    # Runs are shared committee
    # spend, so Observability stays committee-wide — this only makes the shared cost
    # attributable ("who kicked off this Rank"). Nullable + no cascade: a run's cost history
    # must outlive a removed member, so the relationship is nullable. This is attribution,
    # not per-member scope.
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    triggered_by: Mapped[User | None] = relationship()
    passes: Mapped[list[RunPassCost]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunPassCost.id"
    )


class RunPassCost(TimestampMixin, Base):
    """One pass's spend within a completed run — the single source of per-pass cost
    for BOTH pool-level passes (discovery, decompose, match, consolidate) and per-
    application passes (screening, scoring). Every pass writes the same shape here, so the
    Observability cost surfaces read one table instead of stitching together criteria keys,
    summed cache rows, and a JSON blob.

    ``calls`` is fresh model calls (per-dimension units for scoring); ``input_tokens`` /
    ``output_tokens`` / ``cost_usd`` are that fresh spend. ``cached_count`` /
    ``cached_saved_usd`` are the cache side — reused units and their estimated cost on
    the selected route (what caching avoided). A never-cached pass leaves those 0.
    ``model_id`` is the model the pass ran on ("" when the pass made no call this run,
    e.g. a skipped match on a first run).

    ``duration_ms`` is the pass's wall-clock, measured at the pass level,
    NOT summed from parallel calls (that would be CPU time). ``failed_calls`` counts model
    calls that errored: real for the per-application passes (a failure is non-fatal, the
    run continues), ~always 0 for the pool passes (a failure aborts the run before it
    records). Retry counts are deliberately absent — they happen inside the AWS SDK
    (adaptive, max_attempts=5) and aren't surfaced without hooking boto's event system.
    """

    __tablename__ = "run_pass_cost"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("run_cost_ledger.id", ondelete="CASCADE"), index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cached_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_saved_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    run: Mapped[RunCostLedger] = relationship(back_populates="passes")


class Analysis(TimestampMixin, Base):
    """One Rank's shared AI output: the discovered dimensions (``dimension_report``) and the
    pool+prompt fingerprint that flags it out-of-date. This is the compute-once substrate —
    shared across all committee members. Each member's *view* of these dimensions
    (tiers, badges, proposals) lives in a per-member ``MemberRanking`` child, NOT here, so one
    member's tiering never becomes everyone's. The AI-legibility audits (discovery narrative +
    the four pass audits) are large and read one-at-a-time, so they live in a 1:1
    ``AnalysisAudit`` child rather than bloating this row. "The current analysis" is the most
    recent one.
    """

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    # True only when every application in the ranked pool was stamped synthetic.
    synthetic_data: Mapped[bool] = mapped_column(
        default=False, server_default="0", nullable=False
    )
    # The analysis's discovered dimensions (a serialized PoolDimensionReport).
    dimension_report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Everything the ranking depends on — pool + each rank-chain prompt/model — hashed.
    # The next Rank compares it to flag the analysis "out of date". Indexed: read on every estimate.
    rank_inputs_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)

    audit: Mapped[AnalysisAudit | None] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", uselist=False
    )


class MemberRanking(TimestampMixin, Base):
    """One committee member's private view of an ``Analysis``: their importance tiers,
    new/revived-dimension flags, proposals, and requested-pill dismissals — all in ``run_state``.
    Tier weights are always DERIVED from ``run_state.tiers`` (see ``dimension_weights``), never
    stored. Keyed per (analysis, member): a re-rank creates a new Analysis and seeds each
    member a fresh MemberRanking by carrying their prior tiers forward, so each member's tiering
    is independent and versioned with the analysis.
    """

    __tablename__ = "member_rankings"
    __table_args__ = (UniqueConstraint("analysis_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # The member's mutable view: {tiers, new_dimension_keys, proposed_dimensions,
    # acknowledged_requested_keys}. One blob — all written together, tiers is nested.
    run_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    analysis: Mapped[Analysis] = relationship()
    user: Mapped[User] = relationship()


class AnalysisAudit(TimestampMixin, Base):
    """The AI-legibility trail for one Analysis, split off so the hot read path
    (dimensions + tiers) never pulls these large blobs. One row per analysis, populated as the
    chain runs; each field is nullable when that audit was not captured. The ``/ranking/current/
    *-audit`` endpoints are the only readers. ``consolidate`` carries the pass's per-pair
    reasoning (definitions + narrative) — the *merge map* is NOT duplicated here, it lives once
    in ``dimension_aliases`` (the sole merge-truth).
    """

    __tablename__ = "analysis_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    discovery_narrative: Mapped[str | None] = mapped_column(Text)
    match: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    fan_out: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    decompose: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    consolidate: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    analysis: Mapped[Analysis] = relationship(back_populates="audit")


class DimensionAlias(TimestampMixin, Base):
    """A confirmed duplicate dimension key folded into its canonical key.

    The post-score consolidation pass writes one row per merge: ``alias_key`` (the newer
    key retired) → ``canonical_key`` (the older key kept). ``all_known_dimensions``
    resolves through these so the match pass adopts the canonical key on every future
    run — otherwise discovery would re-mint the duplicate and it would re-heal each run.
    ``reason`` is the model's one-line merge justification (audit trail). Resolution
    follows chains to a terminal canonical key, so a later merge of a canonical key
    forwards its existing aliases too.
    """

    __tablename__ = "dimension_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias_key: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvalRun(TimestampMixin, Base):
    """One run of an eval fired from the Evals tab — the durable, queryable record.

    Stores the structured ``result`` (the eval's response model, camelCase JSON as the UI
    reads it) plus ``thinking`` (the streamed NON-judge model reasoning, so we can later
    "eval the eval"). ``prompt_version`` stamps the exact prompt exercised, so a result is
    attributable and trends across a prompt edit are readable. Kept in the DB (not files)
    so "agreement over the last N runs" is a plain query, consistent with how the cost
    ledger and ranking runs already persist operational history. Synthetic-data only.
    """

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    eval_key: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
