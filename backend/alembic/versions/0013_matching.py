"""Matching rounds and candidate snapshots, notifications outbox and job runs (D2).

Revision ID: 0013_matching
Revises: 0012_commission
Create Date: 2026-11-05 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_matching"
down_revision: str | None = "0012_commission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("job_name", sa.Text(), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("items_processed", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed')", name=op.f("ck_job_runs_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
    )
    op.create_index("ix_job_runs_name_started", "job_runs", ["job_name", "started_at"], unique=False)
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("channel IN ('in_app', 'sms')", name=op.f("ck_notifications_channel")),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped', 'read')", name=op.f("ck_notifications_status")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        "ix_notifications_due",
        "notifications",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_notifications_user_status", "notifications", ["user_id", "status", "created_at"], unique=False
    )
    op.create_table(
        "matching_runs",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("run_no", sa.SmallInteger(), nullable=False),
        sa.Column("attempt", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("request_type", sa.Text(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("available_count", sa.Integer(), nullable=False),
        sa.Column("excluded_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("proposal_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "close_reason IS NULL OR close_reason IN ('client_confirmed', 'client_rejected', 'client_timeout', 'master_accepted', 'master_declined', 'master_expired', 'cancelled', 'conflict')",  # noqa: E501
            name=op.f("ck_matching_runs_close_reason"),
        ),
        sa.CheckConstraint("outcome IN ('proposed', 'no_candidates')", name=op.f("ck_matching_runs_outcome")),
        sa.CheckConstraint("run_no BETWEEN 1 AND 3", name=op.f("ck_matching_runs_run_no")),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["service_requests.id"],
            name=op.f("fk_matching_runs_request_id_service_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_matching_runs")),
        sa.UniqueConstraint(
            "request_id", "run_no", "attempt", name=op.f("uq_matching_runs_request_id_run_no_attempt")
        ),
    )
    op.create_index(
        "ix_matching_runs_open_proposal",
        "matching_runs",
        ["proposal_expires_at"],
        unique=False,
        postgresql_where=sa.text("closed_at IS NULL AND outcome = 'proposed'"),
    )
    op.create_table(
        "matching_candidates",
        sa.Column("matching_run_id", sa.Uuid(), nullable=False),
        sa.Column("master_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("distance_km", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("eta_minutes", sa.Integer(), nullable=False),
        sa.Column("eta_source", sa.Text(), nullable=False),
        sa.Column("rating_avg", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("completed_jobs", sa.Integer(), nullable=False),
        sa.Column("role_in_result", sa.Text(), nullable=False),
        sa.Column("chosen_by_client", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "eta_source IN ('routing', 'fallback')", name=op.f("ck_matching_candidates_eta_source")
        ),
        sa.CheckConstraint(
            "role_in_result IN ('proposal', 'alternative', 'not_shown')",
            name=op.f("ck_matching_candidates_role_in_result"),
        ),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["master_profiles.id"],
            name=op.f("fk_matching_candidates_master_id_master_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["matching_run_id"],
            ["matching_runs.id"],
            name=op.f("fk_matching_candidates_matching_run_id_matching_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_matching_candidates")),
    )
    op.create_index(
        "ix_matching_candidates_run_rank", "matching_candidates", ["matching_run_id", "rank"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_matching_candidates_run_rank", table_name="matching_candidates")
    op.drop_table("matching_candidates")
    op.drop_index("ix_matching_runs_open_proposal", table_name="matching_runs")
    op.drop_table("matching_runs")
    op.drop_index("ix_notifications_user_status", table_name="notifications")
    op.drop_index("ix_notifications_due", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_job_runs_name_started", table_name="job_runs")
    op.drop_table("job_runs")
