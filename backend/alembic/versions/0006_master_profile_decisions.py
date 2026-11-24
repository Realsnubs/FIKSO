"""Master profile decisions record who decided, when and why, like the other capability decisions (R-MST-10).

`approved_by`/`approved_at`/`rejection_reason` become `decided_by`/`decided_at`/`decision_reason` (they also
hold a rejection), `version` guards admin decisions against stale views, and the database requires the
deciding admin and the time for `approved` and `rejected` (owner decision, 2026-11-02). Columns are renamed,
so no value is lost.

Revision ID: 0006_master_profile_decisions
Revises: 0005_qualification_renewal
Create Date: 2026-11-02 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_master_profile_decisions"
down_revision: str | None = "0005_qualification_renewal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMES = (
    ("approved_by", "decided_by"),
    ("approved_at", "decided_at"),
    ("rejection_reason", "decision_reason"),
)
DECISION_CHECK = (
    "approval_status NOT IN ('approved', 'rejected') OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)"
)


def upgrade() -> None:
    # A decided profile without a recorded decider is not repaired by inventing one: stop, a human decides.
    undecided = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM master_profiles "
            "WHERE approval_status IN ('approved', 'rejected') "
            "AND (approved_by IS NULL OR approved_at IS NULL)"
        )
    )
    if undecided:
        raise RuntimeError(
            f"{undecided} approved/rejected master profile(s) have no recorded decider or time; "
            "record them before upgrading (no value is guessed)."
        )
    for old, new in RENAMES:
        op.alter_column("master_profiles", old, new_column_name=new)
    op.execute(
        "ALTER TABLE master_profiles RENAME CONSTRAINT fk_master_profiles_approved_by_users "
        "TO fk_master_profiles_decided_by_users"
    )
    op.add_column("master_profiles", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.create_check_constraint(
        op.f("ck_master_profiles_decision_recorded"), "master_profiles", DECISION_CHECK
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_master_profiles_decision_recorded"), "master_profiles", type_="check")
    op.drop_column("master_profiles", "version")
    op.execute(
        "ALTER TABLE master_profiles RENAME CONSTRAINT fk_master_profiles_decided_by_users "
        "TO fk_master_profiles_approved_by_users"
    )
    for old, new in RENAMES:
        op.alter_column("master_profiles", new, new_column_name=old)
