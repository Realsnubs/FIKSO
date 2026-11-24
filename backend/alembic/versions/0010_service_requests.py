"""Client service requests (Stage D1).

Revision ID: 0010_service_requests
Revises: 0009_catalogue_content
Create Date: 2026-11-05 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_service_requests"
down_revision: str | None = "0009_catalogue_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_requests",
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("catalogue_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("commercial_terms_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("request_type", sa.Text(), nullable=False),
        sa.Column("preferred_time_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preferred_time_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("address_formatted", sa.Text(), nullable=False),
        sa.Column("flat", sa.Text(), nullable=True),
        sa.Column("access_info", sa.Text(), nullable=True),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("lon", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("geocode_source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("unserved_reason", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), server_default="app", nullable=False),
        sa.Column("deeplink_w_id", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("current_round", sa.Integer(), server_default="0", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "request_type = 'immediate' OR (preferred_time_from IS NOT NULL AND preferred_time_to IS NOT NULL AND preferred_time_to > preferred_time_from)",  # noqa: E501
            name=op.f("ck_service_requests_reserved_window"),
        ),
        sa.CheckConstraint(
            "request_type IN ('immediate', 'reserved')", name=op.f("ck_service_requests_request_type")
        ),
        sa.CheckConstraint("source IN ('app', 'website_deeplink')", name=op.f("ck_service_requests_source")),
        sa.CheckConstraint(
            "status IN ('draft', 'matching', 'proposed', 'confirmed', 'unserved', 'cancelled')",
            name=op.f("ck_service_requests_status"),
        ),
        sa.CheckConstraint(
            "unserved_reason IS NULL OR unserved_reason IN ('no_candidates', 'rounds_exhausted')",
            name=op.f("ck_service_requests_unserved_reason"),
        ),
        sa.CheckConstraint(
            "char_length(description) BETWEEN 10 AND 2000",
            name=op.f("ck_service_requests_description_length"),
        ),
        sa.CheckConstraint("current_round BETWEEN 0 AND 3", name=op.f("ck_service_requests_current_round")),
        sa.ForeignKeyConstraint(
            ["client_id"], ["users.id"], name=op.f("fk_service_requests_client_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["commercial_terms_id"],
            ["commercial_terms.id"],
            name=op.f("fk_service_requests_commercial_terms_id_commercial_terms"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["catalogue_services.id"],
            name=op.f("fk_service_requests_service_id_catalogue_services"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_requests")),
        sa.UniqueConstraint(
            "client_id", "idempotency_key", name=op.f("uq_service_requests_client_id_idempotency_key")
        ),
    )
    op.create_index(
        "ix_service_requests_client_created", "service_requests", ["client_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_service_requests_status_created", "service_requests", ["status", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_service_requests_status_created", table_name="service_requests")
    op.drop_index("ix_service_requests_client_created", table_name="service_requests")
    op.drop_table("service_requests")
