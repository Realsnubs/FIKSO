"""Public catalogue images, kept apart from private files (Stage C3, OQ-10/11).

Revision ID: 0008_public_media
Revises: 0007_commercial_terms
Create Date: 2026-11-05 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_public_media"
down_revision: str | None = "0007_commercial_terms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "public_media",
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("variants", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("alt", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), server_default="ready", nullable=False),
        sa.Column("rights_basis", sa.Text(), nullable=False),
        sa.Column("rights_reference", sa.Text(), nullable=True),
        sa.Column("consent_given_on", sa.Date(), nullable=True),
        sa.Column("consent_withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("personal_data_checked", sa.Boolean(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "rights_basis <> 'client_consent' OR (rights_reference IS NOT NULL AND consent_given_on IS NOT NULL)",  # noqa: E501
            name=op.f("ck_public_media_consent_recorded"),
        ),
        sa.CheckConstraint(
            "rights_basis IN ('own', 'client_consent', 'licence')", name=op.f("ck_public_media_rights_basis")
        ),
        sa.CheckConstraint("status IN ('ready', 'archived')", name=op.f("ck_public_media_status")),
        sa.CheckConstraint("personal_data_checked", name=op.f("ck_public_media_personal_data_checked")),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_public_media_uploaded_by_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_public_media")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_public_media_storage_key")),
    )


def downgrade() -> None:
    op.drop_table("public_media")
