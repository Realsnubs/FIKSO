"""Versioned, localised page content of specialisations and anonymous catalogue counters (C4, C7).

Revision ID: 0009_catalogue_content
Revises: 0008_public_media
Create Date: 2026-11-05 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_catalogue_content"
down_revision: str | None = "0008_public_media"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalogue_content",
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("published_version_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("entity_type = 'specialisation'", name=op.f("ck_catalogue_content_entity_type")),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f("ck_catalogue_content_slug_format")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalogue_content")),
        sa.UniqueConstraint(
            "entity_type", "entity_id", name=op.f("uq_catalogue_content_entity_type_entity_id")
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_catalogue_content_slug")),
    )
    op.create_table(
        "public_events",
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('catalogue_view', 'specialisation_view', 'service_selected')",
            name=op.f("ck_public_events_event_type"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_public_events")),
    )
    op.create_index(
        "ix_public_events_type_created", "public_events", ["event_type", "created_at"], unique=False
    )
    op.create_table(
        "catalogue_content_versions",
        sa.Column("content_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "state IN ('draft', 'published', 'superseded')", name=op.f("ck_catalogue_content_versions_state")
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["catalogue_content.id"],
            name=op.f("fk_catalogue_content_versions_content_id_catalogue_content"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_catalogue_content_versions_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_by"],
            ["users.id"],
            name=op.f("fk_catalogue_content_versions_published_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalogue_content_versions")),
        sa.UniqueConstraint(
            "content_id", "version_no", name=op.f("uq_catalogue_content_versions_content_id_version_no")
        ),
    )
    op.create_index(
        "uq_catalogue_content_versions_one_draft",
        "catalogue_content_versions",
        ["content_id"],
        unique=True,
        postgresql_where=sa.text("state = 'draft'"),
    )
    op.create_table(
        "content_slug_redirects",
        sa.Column("old_slug", sa.Text(), nullable=False),
        sa.Column("content_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["catalogue_content.id"],
            name=op.f("fk_content_slug_redirects_content_id_catalogue_content"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("old_slug", name=op.f("pk_content_slug_redirects")),
    )
    op.create_foreign_key(
        op.f("fk_catalogue_content_published_version_id_catalogue_content_versions"),
        "catalogue_content",
        "catalogue_content_versions",
        ["published_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_catalogue_content_published_version_id_catalogue_content_versions"),
        "catalogue_content",
        type_="foreignkey",
    )
    op.drop_table("content_slug_redirects")
    op.drop_index("uq_catalogue_content_versions_one_draft", table_name="catalogue_content_versions")
    op.drop_table("catalogue_content_versions")
    op.drop_index("ix_public_events_type_created", table_name="public_events")
    op.drop_table("public_events")
    op.drop_table("catalogue_content")
