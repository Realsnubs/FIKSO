"""Departure records, work segments, work sheets, materials and reviews (D3).

Revision ID: 0015_worksheets
Revises: 0014_orders
Create Date: 2026-11-05 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_worksheets"
down_revision: str | None = "0014_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("master_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name=op.f("ck_reviews_rating")),
        sa.ForeignKeyConstraint(
            ["client_id"], ["users.id"], name=op.f("fk_reviews_client_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["master_profiles.id"],
            name=op.f("fk_reviews_master_id_master_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_reviews_order_id_orders"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
        sa.UniqueConstraint("order_id", name=op.f("uq_reviews_order_id")),
    )
    op.create_table(
        "work_segments",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name=op.f("ck_work_segments_ordered")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_work_segments_order_id_orders"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_segments")),
    )
    op.create_index(
        "uq_work_segments_one_open",
        "work_segments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_table(
        "worksheets",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.Text(), server_default="draft", nullable=False),
        sa.Column("work_description", sa.Text(), nullable=True),
        sa.Column("limitations_explained", sa.Text(), nullable=True),
        sa.Column("is_temporary_repair", sa.Boolean(), nullable=False),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("materials_amount_eur", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("external_costs_eur", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("travel_minutes", sa.Integer(), nullable=True),
        sa.Column("billable_seconds", sa.Integer(), nullable=True),
        sa.Column("labour_amount_eur", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("commission_eur", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("calculation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("finalised_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("state IN ('draft', 'finalised')", name=op.f("ck_worksheets_state")),
        sa.CheckConstraint(
            "materials_amount_eur >= 0 AND external_costs_eur >= 0",
            name=op.f("ck_worksheets_amounts_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_worksheets_order_id_orders"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worksheets")),
        sa.UniqueConstraint("order_id", name=op.f("uq_worksheets_order_id")),
    )
    op.create_table(
        "order_departures",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("master_id", sa.Uuid(), nullable=False),
        sa.Column("departed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_history_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["master_profiles.id"],
            name=op.f("fk_order_departures_master_id_master_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_order_departures_order_id_orders"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["status_history_id"],
            ["order_status_history.id"],
            name=op.f("fk_order_departures_status_history_id_order_status_history"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("order_id", name=op.f("pk_order_departures")),
    )
    op.create_table(
        "worksheet_materials",
        sa.Column("worksheet_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("amount_eur", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("amount_eur >= 0 AND quantity > 0", name=op.f("ck_worksheet_materials_positive")),
        sa.ForeignKeyConstraint(
            ["worksheet_id"],
            ["worksheets.id"],
            name=op.f("fk_worksheet_materials_worksheet_id_worksheets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worksheet_materials")),
    )


def downgrade() -> None:
    op.drop_table("worksheet_materials")
    op.drop_table("order_departures")
    op.drop_table("worksheets")
    op.drop_index("uq_work_segments_one_open", table_name="work_segments")
    op.drop_table("work_segments")
    op.drop_table("reviews")
