"""Opening household bounds and dispatched paid-run ownership."""

import sqlalchemy as sa

from alembic import op

revision = "cc85134ae672"
down_revision = "b69f7e31d425"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("openings", sa.Column("min_children", sa.Integer(), nullable=True))
    op.add_column("openings", sa.Column("max_children", sa.Integer(), nullable=True))
    op.execute("UPDATE openings SET min_children=unit_size_bedrooms-1, max_children=CASE WHEN unit_size_bedrooms=1 THEN 0 END")
    op.execute("""UPDATE openings SET creation_request=json_set(creation_request,
        '$.min_children',json_extract(creation_request,'$.unit_size_bedrooms')-1,
        '$.max_children',CASE WHEN json_extract(creation_request,'$.unit_size_bedrooms')=1 THEN 0 END)
        WHERE json_type(creation_request)='object'""")
    op.add_column("run_lock", sa.Column("dispatched_opening_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("run_lock", "dispatched_opening_id")
    op.execute("""UPDATE openings SET creation_request=json_remove(creation_request,'$.min_children','$.max_children')
        WHERE json_type(creation_request)='object'""")
    op.drop_column("openings", "max_children")
    op.drop_column("openings", "min_children")
