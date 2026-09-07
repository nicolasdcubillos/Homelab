"""Eventos oficiales versionados junto a su evidencia original."""

import sqlalchemy as sa
from alembic import op

revision = "5a7b9d213f41"
down_revision = "4f6a8c102e30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("regime_licenses", sa.Column("evidence_sha256", sa.String(64), nullable=True))
    op.create_table(
        "regime_payload_licenses",
        sa.Column(
            "raw_id", sa.Integer(), sa.ForeignKey("regime_raw_payloads.id"), primary_key=True
        ),
        sa.Column("license_id", sa.String(32), sa.ForeignKey("regime_licenses.id"), nullable=False),
    )
    op.create_table(
        "regime_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(120), nullable=False),
        sa.Column("raw_id", sa.Integer(), sa.ForeignKey("regime_raw_payloads.id"), nullable=False),
        sa.Column("raw_hash", sa.String(64), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source_id", "event_id", "raw_hash", name="uq_regime_event"),
    )
    op.create_index("ix_regime_events_available_at", "regime_events", ["available_at"])


def downgrade() -> None:
    op.drop_index("ix_regime_events_available_at", table_name="regime_events")
    op.drop_table("regime_events")
    op.drop_table("regime_payload_licenses")
    op.drop_column("regime_licenses", "evidence_sha256")
