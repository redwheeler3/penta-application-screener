from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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


class StatusSource(StrEnum):
    UNTOUCHED = "untouched"  # passed rules, AI didn't flag (or hasn't run)
    RULES = "rules"  # deterministic filters set it ineligible (high trust)
    AI = "ai"  # AI screening pass set it ineligible (low trust — needs review)
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
    # Hash of the machine findings (reasons + AI flags) when a human last set the
    # status. Null unless status_source == human. A differing current hash means
    # there are new findings since the human's review (staleness).
    reviewed_fingerprint: Mapped[str | None] = mapped_column(String(64))


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
        ForeignKey("applications.id"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    application: Mapped[Application] = relationship()
    user: Mapped[User] = relationship()


class ApplicationAIResult(TimestampMixin, Base):
    """Cached AI analysis for one application and analysis kind.

    ``cache_key`` hashes application content + model + prompt version, so an
    unchanged application reuses the stored result. ``output`` holds the validated
    structured-output JSON; usage/cost are kept for auditability.
    """

    __tablename__ = "application_ai_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
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
    # disabled rules) at import time, so the dashboard can flag Import out of date
    # when settings change.
    settings_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class RunCostLedger(TimestampMixin, Base):
    """One row per completed AI run (a Screen, full Rank, or score-current update) — the
    header (M13). This is the only honest source of *per-run* cost:
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
    # captured so estimate-vs-actual drift is queryable after the fact — the project has
    # been bitten by an estimate that disagreed with reality (SPEC Pillar 1). 0.0 on runs
    # recorded before this column existed (server_default), and on kinds that had no
    # pre-run estimate surface.
    estimated_usd: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")

    passes: Mapped[list[RunPassCost]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunPassCost.id"
    )


class RunPassCost(TimestampMixin, Base):
    """One pass's spend within a completed run (M13) — the single source of per-pass cost
    for BOTH pool-level passes (discovery, decompose, match, consolidate) and per-
    application passes (screening, scoring). Every pass writes the same shape here, so the
    Insights cost surfaces read one table instead of stitching together criteria keys,
    summed cache rows, and a JSON blob.

    ``calls`` is fresh model calls (per-dimension units for scoring); ``input_tokens`` /
    ``output_tokens`` / ``cost_usd`` are that fresh spend. ``cached_count`` /
    ``cached_saved_usd`` are the cache side — reused units and their original cost (an
    estimate of what caching saved). A never-cached pass leaves those 0. ``model_id`` is
    the model the pass ran on ("" when the pass made no call this run, e.g. a skipped
    match on a first run).

    ``duration_ms`` is the pass's wall-clock (M13 Pillar 3) — measured at the pass level,
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


class RankingRun(TimestampMixin, Base):
    """One Rank: the discovered dimensions (``dimension_report``), the committee's mutable
    view of them (``run_state`` = tiers + new/proposed-dimension flags), and the pool+prompt
    fingerprint that flags the run out-of-date. Tier weights are always DERIVED from
    ``run_state.tiers`` (see ``dimension_weights``), never stored. The AI-legibility audits
    (discovery narrative + the four pass audits) are large and read one-at-a-time, so they
    live in a 1:1 ``RankingRunAudit`` child rather than bloating this row.
    """

    __tablename__ = "ranking_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_runs.id"))
    # The run's discovered dimensions (a serialized PoolDimensionReport).
    dimension_report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Everything the run's ranking depends on — pool + each rank-chain prompt/model — hashed.
    # The next Rank compares it to flag the run "out of date". Indexed: read on every estimate.
    rank_inputs_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    # The committee's mutable view: {tiers, new_dimension_keys, proposed_dimensions}. Kept
    # together as one blob — all written together, and tiers is a nested list-of-dicts.
    run_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    source_sync_run: Mapped[SyncRun | None] = relationship()
    audit: Mapped[RankingRunAudit | None] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )


class RankingRunAudit(TimestampMixin, Base):
    """The AI-legibility trail for one Rank (M13), split from ``RankingRun`` so the hot read
    path (dimensions + tiers) never pulls these large blobs. One row per run, populated as the
    chain runs; each field is null on runs that predate its capture. The ``/ranking/current/
    *-audit`` endpoints are the only readers. ``consolidate`` carries the pass's per-pair
    reasoning (definitions + narrative) — the *merge map* is NOT duplicated here, it lives once
    in ``dimension_aliases`` (the sole merge-truth).
    """

    __tablename__ = "ranking_run_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ranking_runs.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    discovery_narrative: Mapped[str | None] = mapped_column(Text)
    match: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    fan_out: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    decompose: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    consolidate: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    run: Mapped[RankingRun] = relationship(back_populates="audit")


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
