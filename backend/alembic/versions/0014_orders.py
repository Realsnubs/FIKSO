"""Orders, offers and status history (D2).

An order row is created only when the client confirms (option A) and is the single assignment record from
`offered` to `in_progress`. The GiST exclusion constraint makes two overlapping blocking rows of one master
impossible (owner decision Q-FINAL-03); it needs `btree_gist` for the equality on `master_id`.

Revision ID: 0014_orders
Revises: 0013_matching
Create Date: 2026-11-05 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_orders"
down_revision: str | None = "0013_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")
    op.create_table(
        "orders",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("matching_run_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("master_id", sa.Uuid(), nullable=False),
        sa.Column("order_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("estimated_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estimated_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("busy_range", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("en_route_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("work_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("work_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_by_role", sa.Text(), nullable=True),
        sa.Column("commission_rate_snapshot", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("hourly_rate_snapshot", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("minimum_order_snapshot", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        postgresql.ExcludeConstraint(
            (sa.column("master_id"), "="),
            (sa.column("busy_range"), "&&"),
            where=sa.text("status IN ('offered', 'accepted', 'scheduled', 'en_route', 'in_progress')"),
            using="gist",
            name="ex_orders_master_busy_range",
        ),
        sa.CheckConstraint("order_type IN ('immediate', 'reserved')", name=op.f("ck_orders_order_type")),
        sa.CheckConstraint(
            "status IN ('offered', 'declined', 'expired', 'accepted', 'scheduled', 'en_route', 'in_progress', 'completed', 'reviewed', 'cancelled')",  # noqa: E501
            name=op.f("ck_orders_status"),
        ),
        sa.CheckConstraint("NOT isempty(busy_range)", name=op.f("ck_orders_busy_range_not_empty")),
        sa.ForeignKeyConstraint(
            ["client_id"], ["users.id"], name=op.f("fk_orders_client_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["master_profiles.id"],
            name=op.f("fk_orders_master_id_master_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["matching_run_id"],
            ["matching_runs.id"],
            name=op.f("fk_orders_matching_run_id_matching_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["service_requests.id"],
            name=op.f("fk_orders_request_id_service_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
    )
    op.create_index("ix_orders_client_created", "orders", ["client_id", "created_at"], unique=False)
    op.create_index("ix_orders_master_status", "orders", ["master_id", "status"], unique=False)
    op.create_index("ix_orders_status_updated", "orders", ["status", "updated_at"], unique=False)
    op.create_index(
        "uq_orders_one_live_per_request",
        "orders",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('declined', 'expired', 'cancelled')"),
    )
    op.create_table(
        "order_offers",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("master_id", sa.Uuid(), nullable=False),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "response IS NULL OR response IN ('accepted', 'declined', 'expired', 'cancelled')",
            name=op.f("ck_order_offers_response"),
        ),
        sa.CheckConstraint("expires_at > offered_at", name=op.f("ck_order_offers_expiry_after_offer")),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["master_profiles.id"],
            name=op.f("fk_order_offers_master_id_master_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_order_offers_order_id_orders"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_offers")),
        sa.UniqueConstraint("order_id", name=op.f("uq_order_offers_order_id")),
    )
    op.create_index(
        "ix_order_offers_open",
        "order_offers",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("response IS NULL"),
    )
    op.create_table(
        "order_status_history",
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("entity", sa.Text(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('user', 'service_principal', 'system')",
            name=op.f("ck_order_status_history_actor_type"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_status_history_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["service_requests.id"],
            name=op.f("fk_order_status_history_request_id_service_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_status_history")),
    )
    op.create_index(
        "ix_order_status_history_order", "order_status_history", ["order_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_order_status_history_request", "order_status_history", ["request_id", "created_at"], unique=False
    )
    op.execute(
        "CREATE TRIGGER order_status_history_append_only BEFORE UPDATE OR DELETE ON order_status_history FOR EACH ROW EXECUTE FUNCTION forbid_modification();"  # noqa: E501
    )
    op.create_foreign_key(
        op.f("fk_commission_ledger_order_id_orders"),
        "commission_ledger",
        "orders",
        ["order_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_commission_ledger_order_id_orders"), "commission_ledger", type_="foreignkey")
    op.execute("DROP TRIGGER IF EXISTS order_status_history_append_only ON order_status_history;")
    op.drop_index("ix_order_status_history_request", table_name="order_status_history")
    op.drop_index("ix_order_status_history_order", table_name="order_status_history")
    op.drop_table("order_status_history")
    op.drop_index("ix_order_offers_open", table_name="order_offers")
    op.drop_table("order_offers")
    op.drop_index("uq_orders_one_live_per_request", table_name="orders")
    op.drop_index("ix_orders_status_updated", table_name="orders")
    op.drop_index("ix_orders_master_status", table_name="orders")
    op.drop_index("ix_orders_client_created", table_name="orders")
    op.drop_table("orders")
