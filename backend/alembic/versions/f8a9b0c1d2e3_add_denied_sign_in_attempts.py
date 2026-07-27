"""add denied sign-in attempts

Admin-visible access audit for Google accounts rejected by the allowlist. The
application removes entries older than one year whenever it records or reads
this data.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "denied_sign_in_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("google_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_denied_sign_in_attempts_google_subject"),
        "denied_sign_in_attempts",
        ["google_subject"],
    )
    op.create_index(
        op.f("ix_denied_sign_in_attempts_email"),
        "denied_sign_in_attempts",
        ["email"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_denied_sign_in_attempts_email"), table_name="denied_sign_in_attempts")
    op.drop_index(
        op.f("ix_denied_sign_in_attempts_google_subject"),
        table_name="denied_sign_in_attempts",
    )
    op.drop_table("denied_sign_in_attempts")
