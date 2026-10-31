"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-31 18:44:40.382993
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.execute("INSERT INTO tenants (id, slug, name) VALUES (1, 'default', 'Default')")
    op.execute("SELECT setval(pg_get_serial_sequence('tenants', 'id'), 1)")
    op.create_table(
        "watch_keys",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("destination", sa.String(length=3), nullable=False),
        sa.Column("date_mode", sa.String(length=8), nullable=False),
        sa.Column("depart_date", sa.Date(), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=True),
        sa.Column("direct_only", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column(
            "next_check_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("active_watch_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("date_mode IN ('exact','month')", name=op.f("ck_watch_keys_date_mode")),
        sa.CheckConstraint("active_watch_count >= 0", name=op.f("ck_watch_keys_count_nonneg")),
        sa.CheckConstraint(
            "char_length(origin) = 3 AND char_length(destination) = 3", name=op.f("ck_watch_keys_iata")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watch_keys")),
        sa.UniqueConstraint(
            "origin",
            "destination",
            "date_mode",
            "depart_date",
            "return_date",
            "direct_only",
            "currency",
            name="uq_watch_keys_signature",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_watch_keys_due",
        "watch_keys",
        ["next_check_at"],
        unique=False,
        postgresql_where=sa.text("active_watch_count > 0"),
    )
    op.create_table(
        "price_points",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("watch_key_id", sa.BigInteger(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("depart_date", sa.Date(), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=True),
        sa.Column("airline", sa.String(length=8), nullable=True),
        sa.Column("transfers", sa.SmallInteger(), nullable=True),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("found_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["watch_key_id"],
            ["watch_keys.id"],
            name=op.f("fk_price_points_watch_key_id_watch_keys"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_points")),
    )
    op.create_index(
        "ix_price_points_key_time",
        "price_points",
        ["watch_key_id", sa.literal_column("observed_at DESC")],
        unique=False,
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.String(length=2), server_default="az", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("home_iata", sa.String(length=3), nullable=True),
        sa.Column("plan", sa.String(length=8), server_default="free", nullable=False),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("language IN ('az','ru','en')", name=op.f("ck_users_language")),
        sa.CheckConstraint("plan IN ('free','pro')", name=op.f("ck_users_plan")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_users_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("tenant_id", "telegram_id", name="uq_users_tenant_telegram"),
    )
    op.create_table(
        "watches",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("watch_key_id", sa.BigInteger(), nullable=False),
        sa.Column("target_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("status", sa.String(length=8), server_default="active", nullable=False),
        sa.Column("pause_reason", sa.String(length=16), nullable=True),
        sa.Column("armed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_notified_price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active','paused','expired')", name=op.f("ck_watches_status")),
        sa.CheckConstraint("target_price > 0", name=op.f("ck_watches_target_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_watches_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["watch_key_id"],
            ["watch_keys.id"],
            name=op.f("fk_watches_watch_key_id_watch_keys"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watches")),
        sa.UniqueConstraint("user_id", "watch_key_id", name="uq_watches_user_key"),
    )
    op.create_index(
        "ix_watches_key_active",
        "watches",
        ["watch_key_id", "target_price"],
        unique=False,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_watches_user", "watches", ["user_id"], unique=False)
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("watch_id", sa.BigInteger(), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.String(length=8), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("feedback", sa.SmallInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','sending','sent','failed','skipped')", name=op.f("ck_notifications_status")
        ),
        sa.CheckConstraint("feedback IN (-1, 1)", name=op.f("ck_notifications_feedback")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["watch_id"], ["watches.id"], name=op.f("fk_notifications_watch_id_watches"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("dedup_key", name="uq_notifications_dedup_key"),
    )
    op.create_index(
        "ix_notifications_queue",
        "notifications",
        ["priority", "available_at", "id"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending','sending')"),
    )
    op.create_index(
        "ix_notifications_user_created",
        "notifications",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )

    # --- watch_keys.active_watch_count: DB trigger ilə saxlanılır (əl ilə yenilənmir) ---
    # Əvvəlki dizaynda sayğac tətbiq kodunda yenilənməli idi və sürüşürdü. Trigger bunu aradan qaldırır.
    op.execute(
        """
        CREATE FUNCTION watches_sync_active_count() RETURNS trigger AS $$
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.status = 'active' THEN
                UPDATE watch_keys SET active_watch_count = active_watch_count - 1
                WHERE id = OLD.watch_key_id;
            END IF;
            IF TG_OP IN ('UPDATE', 'INSERT') AND NEW.status = 'active' THEN
                UPDATE watch_keys SET active_watch_count = active_watch_count + 1
                WHERE id = NEW.watch_key_id;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_watches_count_ins AFTER INSERT ON watches "
        "FOR EACH ROW EXECUTE FUNCTION watches_sync_active_count()"
    )
    op.execute(
        "CREATE TRIGGER trg_watches_count_del AFTER DELETE ON watches "
        "FOR EACH ROW EXECUTE FUNCTION watches_sync_active_count()"
    )
    op.execute(
        "CREATE TRIGGER trg_watches_count_upd AFTER UPDATE ON watches FOR EACH ROW "
        "WHEN (OLD.status IS DISTINCT FROM NEW.status "
        "OR OLD.watch_key_id IS DISTINCT FROM NEW.watch_key_id) "
        "EXECUTE FUNCTION watches_sync_active_count()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_watches_count_upd ON watches")
    op.execute("DROP TRIGGER IF EXISTS trg_watches_count_del ON watches")
    op.execute("DROP TRIGGER IF EXISTS trg_watches_count_ins ON watches")
    op.execute("DROP FUNCTION IF EXISTS watches_sync_active_count()")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_index(
        "ix_notifications_queue",
        table_name="notifications",
        postgresql_where=sa.text("status IN ('pending','sending')"),
    )
    op.drop_table("notifications")
    op.drop_index("ix_watches_user", table_name="watches")
    op.drop_index(
        "ix_watches_key_active", table_name="watches", postgresql_where=sa.text("status = 'active'")
    )
    op.drop_table("watches")
    op.drop_table("users")
    op.drop_index("ix_price_points_key_time", table_name="price_points")
    op.drop_table("price_points")
    op.drop_index(
        "ix_watch_keys_due", table_name="watch_keys", postgresql_where=sa.text("active_watch_count > 0")
    )
    op.drop_table("watch_keys")
    op.drop_table("tenants")
