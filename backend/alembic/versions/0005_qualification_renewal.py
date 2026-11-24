"""Allow renewing an expired qualification: only one pending submission per master and qualification.

The 0004 index allowed one row that was `submitted` *or* `verified`, which blocked a renewal while the expired
verified row stays unchanged in history (owner decision, 2026-11-02). Now the database guarantees at most
one `submitted` row; "no new submission while a valid verified one exists" is checked by the service under a
lock on the master row, because validity depends on the date.

Revision ID: 0005_qualification_renewal
Revises: 0004_master_capabilities
Create Date: 2026-11-02 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_qualification_renewal"
down_revision: str | None = "0004_master_capabilities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_master_qualifications_open", table_name="master_qualifications")
    op.create_index(
        "uq_master_qualifications_pending",
        "master_qualifications",
        ["master_id", "qualification_id"],
        unique=True,
        postgresql_where=sa.text("status = 'submitted'"),
    )


def downgrade() -> None:
    # Fails (and changes nothing) once a renewal exists next to its expired verified row; no data is dropped.
    op.drop_index("uq_master_qualifications_pending", table_name="master_qualifications")
    op.create_index(
        "uq_master_qualifications_open",
        "master_qualifications",
        ["master_id", "qualification_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('submitted', 'verified')"),
    )
