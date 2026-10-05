"""Retain cached results by producer or selected consumer without changing provenance.

Revision ID: b58f6d20c314
Revises: a47e5c19b203
"""

import sqlalchemy as sa

from alembic import op

revision = "b58f6d20c314"
down_revision = "a47e5c19b203"
branch_labels = None
depends_on = None
NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def upgrade() -> None:
    connection = op.get_bind()
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("Result-table rebuild requires foreign_keys=OFF to preserve selected references.")
    sequence = connection.exec_driver_sql("SELECT seq FROM sqlite_sequence WHERE name='application_ai_results'").scalar()
    with op.batch_alter_table("application_ai_results", naming_convention=NAMING,
                             table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_constraint("fk_application_ai_results_application_id_applications", type_="foreignkey")
        batch.drop_index("ix_application_ai_results_application_id")
        batch.alter_column("application_id", new_column_name="producer_application_id", existing_type=sa.Integer())
    op.create_index("ix_application_ai_results_producer_application_id", "application_ai_results", ["producer_application_id"])
    if sequence is not None:
        connection.execute(sa.text("UPDATE sqlite_sequence SET seq=MAX(seq, :seq) WHERE name='application_ai_results'"), {"seq": sequence})
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("Result-retention migration left an invalid foreign key.")


def downgrade() -> None:
    raise RuntimeError("Producer identities may outlive their applications; this migration cannot safely restore a cascading FK.")
