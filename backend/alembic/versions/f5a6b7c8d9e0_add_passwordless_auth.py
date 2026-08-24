"""add passwordless authentication records

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: str | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    identity_kind = sa.Enum("applicant", "committee", name="passwordlessidentitykind")
    magic_link_purpose = sa.Enum(
        "applicant_access",
        "committee_access",
        "email_change",
        name="magiclinkpurpose",
    )

    op.create_table(
        "magic_link_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_kind", identity_kind, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("purpose", magic_link_purpose, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(identity_kind = 'applicant' AND application_id IS NOT NULL AND user_id IS NULL) "
            "OR (identity_kind = 'committee' AND user_id IS NOT NULL AND application_id IS NULL)",
            name="ck_magic_link_token_identity",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_magic_link_tokens_identity_kind",
        "magic_link_tokens",
        ["identity_kind"],
    )
    op.create_index("ix_magic_link_tokens_email", "magic_link_tokens", ["email"])
    op.create_index(
        "ix_magic_link_tokens_application_id",
        "magic_link_tokens",
        ["application_id"],
    )
    op.create_index("ix_magic_link_tokens_user_id", "magic_link_tokens", ["user_id"])
    op.create_index(
        "ix_magic_link_tokens_token_hash",
        "magic_link_tokens",
        ["token_hash"],
        unique=True,
    )

    op.create_table(
        "browser_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_kind", identity_kind, nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recently_authenticated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(identity_kind = 'applicant' AND application_id IS NOT NULL AND user_id IS NULL) "
            "OR (identity_kind = 'committee' AND user_id IS NOT NULL AND application_id IS NULL)",
            name="ck_browser_session_identity",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_browser_sessions_identity_kind",
        "browser_sessions",
        ["identity_kind"],
    )
    op.create_index(
        "ix_browser_sessions_application_id",
        "browser_sessions",
        ["application_id"],
    )
    op.create_index("ix_browser_sessions_user_id", "browser_sessions", ["user_id"])
    op.create_index(
        "ix_browser_sessions_token_hash",
        "browser_sessions",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_browser_sessions_token_hash", table_name="browser_sessions")
    op.drop_index("ix_browser_sessions_user_id", table_name="browser_sessions")
    op.drop_index("ix_browser_sessions_application_id", table_name="browser_sessions")
    op.drop_index("ix_browser_sessions_identity_kind", table_name="browser_sessions")
    op.drop_table("browser_sessions")

    op.drop_index("ix_magic_link_tokens_token_hash", table_name="magic_link_tokens")
    op.drop_index("ix_magic_link_tokens_user_id", table_name="magic_link_tokens")
    op.drop_index("ix_magic_link_tokens_application_id", table_name="magic_link_tokens")
    op.drop_index("ix_magic_link_tokens_email", table_name="magic_link_tokens")
    op.drop_index("ix_magic_link_tokens_identity_kind", table_name="magic_link_tokens")
    op.drop_table("magic_link_tokens")
