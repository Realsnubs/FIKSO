"""Commission settings, append-only ledger (balance model), limit changes and the balance view (P2).

`commission_ledger.order_id` gets its foreign key in 0014, when `orders` exists.

Revision ID: 0012_commission
Revises: 0011_master_availability
Create Date: 2026-11-05 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_commission"
down_revision: str | None = "0011_master_availability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commission_settings",
        sa.Column("rate", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("default_limit_eur", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "effective_from", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("default_limit_eur >= 0", name=op.f("ck_commission_settings_default_limit")),
        sa.CheckConstraint("rate >= 0 AND rate <= 1", name=op.f("ck_commission_settings_rate")),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name=op.f("fk_commission_settings_changed_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commission_settings")),
    )
    op.create_table(
        "commission_limit_changes",
        sa.Column("master_id", sa.Uuid(), nullable=False),
        sa.Column("old_limit_eur", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("new_limit_eur", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name=op.f("fk_commission_limit_changes_changed_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["master_profiles.id"],
            name=op.f("fk_commission_limit_changes_master_id_master_profiles"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commission_limit_changes")),
    )
    op.create_table(
        "commission_ledger",
        sa.Column("master_id", sa.Uuid(), nullable=False),
        sa.Column("entry_type", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("base_labour_eur", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("rate", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("amount_eur", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("payment_method", sa.Text(), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(entry_type = 'charge' AND amount_eur > 0 AND order_id IS NOT NULL AND base_labour_eur IS NOT NULL AND rate IS NOT NULL) OR (entry_type = 'payment' AND amount_eur < 0 AND order_id IS NULL AND payment_method IN ('cash', 'bank_transfer') AND paid_on IS NOT NULL) OR (entry_type = 'adjustment' AND amount_eur <> 0 AND reason IS NOT NULL)",  # noqa: E501
            name=op.f("ck_commission_ledger_entry_shape"),
        ),
        sa.CheckConstraint(
            "entry_type IN ('charge', 'payment', 'adjustment')", name=op.f("ck_commission_ledger_entry_type")
        ),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["master_profiles.id"],
            name=op.f("fk_commission_ledger_master_id_master_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["users.id"],
            name=op.f("fk_commission_ledger_recorded_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commission_ledger")),
    )
    op.create_index(
        "ix_commission_ledger_master_created", "commission_ledger", ["master_id", "created_at"], unique=False
    )
    op.create_index(
        "uq_commission_ledger_charge_order",
        "commission_ledger",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("entry_type = 'charge'"),
    )
    op.execute(
        "CREATE TRIGGER commission_ledger_append_only BEFORE UPDATE OR DELETE ON commission_ledger FOR EACH ROW EXECUTE FUNCTION forbid_modification();"  # noqa: E501
    )
    op.execute(
        "CREATE TRIGGER commission_limit_changes_append_only BEFORE UPDATE OR DELETE ON commission_limit_changes FOR EACH ROW EXECUTE FUNCTION forbid_modification();"  # noqa: E501
    )
    op.execute(
        "INSERT INTO commission_settings (id, rate, default_limit_eur, reason) "
        "VALUES (gen_random_uuid(), 0.2500, 100.00, 'Initial values R-COM-01/02')"
    )
    op.execute(
        "CREATE VIEW v_master_commission_balance AS "
        "SELECT m.id AS master_id, COALESCE(SUM(l.amount_eur), 0)::numeric(12, 2) AS balance_eur "
        "FROM master_profiles m LEFT JOIN commission_ledger l ON l.master_id = m.id GROUP BY m.id"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_master_commission_balance;")
    op.execute("DROP TRIGGER IF EXISTS commission_limit_changes_append_only ON commission_limit_changes;")
    op.execute("DROP TRIGGER IF EXISTS commission_ledger_append_only ON commission_ledger;")
    op.drop_index("uq_commission_ledger_charge_order", table_name="commission_ledger")
    op.drop_index("ix_commission_ledger_master_created", table_name="commission_ledger")
    op.drop_table("commission_ledger")
    op.drop_table("commission_limit_changes")
    op.drop_table("commission_settings")
