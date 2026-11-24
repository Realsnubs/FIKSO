"""Ordering without a password (owner decision 2026-11-24).

A client may order with name, phone and e-mail only: the account is created without a password, the client
stays signed in on that device, can set a password later and can sign in elsewhere with a one-time SMS code.

guest clients

Revision ID: 0018_guest_clients
Revises: 0017_cities_languages
Create Date: 2026-11-24 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_guest_clients"
down_revision: str | None = "0017_cities_languages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)
    # Only clients may be password-less; masters and admins always sign in with a password.
    op.create_check_constraint(
        op.f("ck_users_password_role"), "users", "password_hash IS NOT NULL OR role = 'client'"
    )
    op.create_table(
        "login_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_login_codes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_codes")),
    )
    op.create_index(
        "ix_login_codes_user_id_open", "login_codes", ["user_id"], postgresql_where=sa.text("used_at IS NULL")
    )


def downgrade() -> None:
    op.drop_index("ix_login_codes_user_id_open", table_name="login_codes")
    op.drop_table("login_codes")
    op.drop_constraint(op.f("ck_users_password_role"), "users", type_="check")
    # Refuses while password-less accounts exist: they would have no way to sign in.
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
