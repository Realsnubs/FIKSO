"""Public commercial terms with history and operational settings (Stage C1).

Seeds the owner-approved terms: 40 €/hour, minimum order value 40 € (floor of the labour amount), and the
materials line in LV/EN/RU. `system_settings` holds timeouts and matching parameters (OPEN_QUESTIONS
Q-FINAL-02).

Revision ID: 0007_commercial_terms
Revises: 0006_master_profile_decisions
Create Date: 2026-11-05 09:00:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_commercial_terms"
down_revision: str | None = "0006_master_profile_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MATERIALS_NOTES = {
    "materials": {
        "lv": "Materiāli un palīgmateriāli tiek apmaksāti atsevišķi.",
        "en": "Materials and consumables are paid separately.",
        "ru": "Материалы и расходные материалы оплачиваются отдельно.",
    }
}
# Timeouts are owner decisions (Q-D2-3, Q-FINAL-02). The immediate-job duration and the buffer between
# orders are
# still open (Q-D2-1): the values below are working assumptions, editable without a deploy.
SETTINGS = {
    "client_confirmation_minutes": {"immediate": 5, "reserved": 30},
    "master_response_minutes": {"immediate": 10, "reserved": 120},
    "matching": {
        "max_rounds": 3,
        "top_k": 10,
        "fallback_speed_kmh": 30,
        "alternative_margin_minutes": 10,
        "max_alternatives": 2,
        "location_fresh_minutes": 15,
    },
    "immediate_job_minutes": 120,
    "order_buffer_minutes": 0,
    "request_photos": {"max_files": 5, "max_bytes": 10485760},
}


def upgrade() -> None:
    op.create_table(
        "commercial_terms",
        sa.Column("hourly_rate_eur", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("minimum_order_eur", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("public_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "effective_from", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("hourly_rate_eur > 0", name=op.f("ck_commercial_terms_hourly_rate")),
        sa.CheckConstraint("minimum_order_eur >= 0", name=op.f("ck_commercial_terms_minimum_order")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_commercial_terms_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commercial_terms")),
    )
    op.create_index(
        "ix_commercial_terms_effective_from", "commercial_terms", ["effective_from"], unique=False
    )
    op.create_table(
        "system_settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_system_settings_updated_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_settings")),
    )
    op.execute(
        "CREATE TRIGGER commercial_terms_append_only BEFORE UPDATE OR DELETE ON commercial_terms FOR EACH ROW EXECUTE FUNCTION forbid_modification();"  # noqa: E501
    )
    op.execute(
        sa.text(
            "INSERT INTO commercial_terms (id, hourly_rate_eur, minimum_order_eur, public_notes, reason) "
            "VALUES (gen_random_uuid(), 40.00, 40.00, CAST(:notes AS jsonb), 'Owner decision 2026-11-04')"
        ).bindparams(notes=json.dumps(MATERIALS_NOTES, ensure_ascii=False))
    )
    for key, value in SETTINGS.items():
        op.execute(
            sa.text(
                "INSERT INTO system_settings (key, value) VALUES (:key, CAST(:value AS jsonb))"
            ).bindparams(key=key, value=json.dumps(value))
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS commercial_terms_append_only ON commercial_terms;")
    op.drop_table("system_settings")
    op.drop_index("ix_commercial_terms_effective_from", table_name="commercial_terms")
    op.drop_table("commercial_terms")
