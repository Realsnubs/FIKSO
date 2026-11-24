"""Master availability modes, Busy, work zone, rating counters and latest location (P1, step 4b).

Revision ID: 0011_master_availability
Revises: 0010_service_requests
Create Date: 2026-11-05 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_master_availability"
down_revision: str | None = "0010_service_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "master_locations",
        sa.Column("master_id", sa.Uuid(), nullable=False),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("lon", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("accuracy_m", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180",
            name=op.f("ck_master_locations_coordinates"),
        ),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["master_profiles.id"],
            name=op.f("fk_master_locations_master_id_master_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("master_id", name=op.f("pk_master_locations")),
    )
    op.add_column("master_profiles", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "master_profiles",
        sa.Column("availability_mode", sa.Text(), server_default="unavailable", nullable=False),
    )
    op.add_column(
        "master_profiles", sa.Column("is_busy", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("master_profiles", sa.Column("busy_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "master_profiles", sa.Column("work_zone_center_lat", sa.Numeric(precision=9, scale=6), nullable=True)
    )
    op.add_column(
        "master_profiles", sa.Column("work_zone_center_lon", sa.Numeric(precision=9, scale=6), nullable=True)
    )
    op.add_column(
        "master_profiles", sa.Column("work_zone_radius_km", sa.Numeric(precision=5, scale=1), nullable=True)
    )
    op.add_column("master_profiles", sa.Column("rating_avg", sa.Numeric(precision=3, scale=2), nullable=True))
    op.add_column(
        "master_profiles", sa.Column("rating_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "master_profiles", sa.Column("completed_jobs", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "master_profiles",
        sa.Column(
            "commission_limit_eur", sa.Numeric(precision=12, scale=2), server_default="100.00", nullable=False
        ),
    )
    op.create_index(
        "ix_master_profiles_matching",
        "master_profiles",
        ["approval_status", "availability_mode", "is_busy"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_master_profiles_matching", table_name="master_profiles")
    op.drop_column("master_profiles", "commission_limit_eur")
    op.drop_column("master_profiles", "completed_jobs")
    op.drop_column("master_profiles", "rating_count")
    op.drop_column("master_profiles", "rating_avg")
    op.drop_column("master_profiles", "work_zone_radius_km")
    op.drop_column("master_profiles", "work_zone_center_lon")
    op.drop_column("master_profiles", "work_zone_center_lat")
    op.drop_column("master_profiles", "busy_since")
    op.drop_column("master_profiles", "is_busy")
    op.drop_column("master_profiles", "availability_mode")
    op.drop_column("master_profiles", "description")
    op.drop_table("master_locations")
