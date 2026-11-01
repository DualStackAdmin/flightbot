"""watch_keys.stay_min / stay_max: round trips by month with a length of stay

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_OLD_COLS = ["origin", "destination", "date_mode", "depart_date", "return_date", "direct_only", "currency"]


def upgrade() -> None:
    op.add_column("watch_keys", sa.Column("stay_min", sa.SmallInteger(), nullable=True))
    op.add_column("watch_keys", sa.Column("stay_max", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "ck_watch_keys_stay_range",
        "watch_keys",
        "(stay_min IS NULL AND stay_max IS NULL) OR "
        "(stay_min BETWEEN 1 AND 30 AND stay_max BETWEEN stay_min AND 30)",
    )
    # The stay is part of the dedup signature: "7 days" and "14 days" are different provider queries.
    op.drop_constraint("uq_watch_keys_signature", "watch_keys", type_="unique")
    op.create_unique_constraint(
        "uq_watch_keys_signature",
        "watch_keys",
        [*_OLD_COLS, "stay_min", "stay_max"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.execute("DELETE FROM watch_keys WHERE stay_min IS NOT NULL")
    op.drop_constraint("uq_watch_keys_signature", "watch_keys", type_="unique")
    op.create_unique_constraint(
        "uq_watch_keys_signature", "watch_keys", _OLD_COLS, postgresql_nulls_not_distinct=True
    )
    op.drop_constraint("ck_watch_keys_stay_range", "watch_keys", type_="check")
    op.drop_column("watch_keys", "stay_max")
    op.drop_column("watch_keys", "stay_min")
