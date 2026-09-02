"""protect the permanent seed admin

Revision ID: 2d3e4f5a6b7c
Revises: 1c2d3e4f5a6b
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2d3e4f5a6b7c"
down_revision: str | None = "1c2d3e4f5a6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOUNDING_ADMIN_EMAIL = "jeffo@jeffo.net"


def upgrade() -> None:
    with op.batch_alter_table("access_allowlist") as batch:
        batch.add_column(
            sa.Column(
                "is_seed_admin",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )

    connection = op.get_bind()
    existing_id = connection.execute(
        sa.text("SELECT id FROM access_allowlist WHERE email = :email"),
        {"email": _FOUNDING_ADMIN_EMAIL},
    ).scalar_one_or_none()
    if existing_id is None:
        connection.execute(
            sa.text(
                "INSERT INTO access_allowlist "
                "(email, role, is_seed_admin, created_at, updated_at) "
                "VALUES (:email, 'admin', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"email": _FOUNDING_ADMIN_EMAIL},
        )
    else:
        connection.execute(
            sa.text(
                "UPDATE access_allowlist SET role = 'admin', is_seed_admin = true "
                "WHERE id = :id"
            ),
            {"id": existing_id},
        )
    connection.execute(
        sa.text(
            "UPDATE users SET role = 'admin', is_active = true "
            "WHERE email = :email"
        ),
        {"email": _FOUNDING_ADMIN_EMAIL},
    )


def downgrade() -> None:
    with op.batch_alter_table("access_allowlist") as batch:
        batch.drop_column("is_seed_admin")
