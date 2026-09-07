"""market regime compartido

Revision ID: 4f6a8c102e30
Revises: 3871b415f74d
Create Date: 2026-09-07 13:30:52.126268
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import homelab_dashboard.db

revision: str = "4f6a8c102e30"
down_revision: str | None = "3871b415f74d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "regime_backtest_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "regime_licenses",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("valid_until", homelab_dashboard.db.UtcDateTime(), nullable=True),
        sa.Column("created_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.Column("revoked_at", homelab_dashboard.db.UtcDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("regime_licenses", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_regime_licenses_source_id"), ["source_id"], unique=False
        )

    op.create_table(
        "regime_model_versions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "regime_raw_payloads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("compressed", sa.LargeBinary(), nullable=False),
        sa.Column("ingested_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "sha256", name="uq_regime_raw"),
    )
    op.create_table(
        "regime_source_state",
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("last_attempt_at", homelab_dashboard.db.UtcDateTime(), nullable=True),
        sa.Column("last_success_at", homelab_dashboard.db.UtcDateTime(), nullable=True),
        sa.Column("budget_day", sa.String(length=10), nullable=False),
        sa.Column("daily_requests", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.create_table(
        "regime_transitions",
        sa.Column("horizon", sa.String(length=16), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("updated_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("horizon"),
    )
    op.create_table(
        "regime_access",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("granted_by", sa.String(length=32), nullable=True),
        sa.Column("created_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.CheckConstraint("level IN ('viewer', 'operator')"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "regime_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=32), nullable=True),
        sa.CheckConstraint("id = 1 AND version >= 1"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "regime_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("series_id", sa.String(length=64), nullable=False),
        sa.Column("period", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=80), nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=False),
        sa.Column("frequency", sa.String(length=16), nullable=False),
        sa.Column("observed_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.Column("published_at", homelab_dashboard.db.UtcDateTime(), nullable=True),
        sa.Column("available_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.Column("ingested_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.Column("vintage", sa.String(length=120), nullable=False),
        sa.Column("timestamp_precision", sa.String(length=16), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("raw_hash", sa.String(length=64), nullable=False),
        sa.Column("quality", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["raw_id"],
            ["regime_raw_payloads.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "series_id", "period", "vintage", "raw_hash", name="uq_regime_observation"
        ),
    )
    with op.batch_alter_table("regime_observations", schema=None) as batch_op:
        batch_op.create_index(
            "ix_regime_observation_asof", ["series_id", "available_at", "observed_at"], unique=False
        )

    op.create_table(
        "regime_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=True),
        sa.Column("requested_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.Column("cutoff", homelab_dashboard.db.UtcDateTime(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=120), nullable=True),
        sa.Column("lease_until", homelab_dashboard.db.UtcDateTime(), nullable=True),
        sa.Column("started_at", homelab_dashboard.db.UtcDateTime(), nullable=True),
        sa.Column("finished_at", homelab_dashboard.db.UtcDateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    with op.batch_alter_table("regime_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_regime_runs_status"), ["status"], unique=False)

    op.create_table(
        "regime_snapshots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("as_of", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.Column("created_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["regime_model_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("regime_snapshots", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_regime_snapshots_as_of"), ["as_of"], unique=False)

    op.create_table(
        "regime_subscriptions",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("email", sa.Boolean(), nullable=False),
        sa.Column("whatsapp", sa.Boolean(), nullable=False),
        sa.Column("consents", sa.JSON(), nullable=False),
        sa.Column("horizons", sa.JSON(), nullable=False),
        sa.Column("updated_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "regime_reports",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("week_key", sa.String(length=16), nullable=False),
        sa.Column("snapshot_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["regime_snapshots.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("week_key"),
    )
    op.create_table(
        "regime_outbox",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("report_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("destination_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", homelab_dashboard.db.UtcDateTime(), nullable=False),
        sa.Column("next_attempt_at", homelab_dashboard.db.UtcDateTime(), nullable=True),
        sa.Column("lease_until", homelab_dashboard.db.UtcDateTime(), nullable=True),
        sa.Column("provider_id", sa.String(length=256), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["regime_reports.id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "user_id", "channel", name="uq_regime_delivery"),
    )
    with op.batch_alter_table("regime_outbox", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_regime_outbox_user_id"), ["user_id"], unique=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("regime_outbox", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_regime_outbox_user_id"))

    op.drop_table("regime_outbox")
    op.drop_table("regime_reports")
    op.drop_table("regime_subscriptions")
    with op.batch_alter_table("regime_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_regime_snapshots_as_of"))

    op.drop_table("regime_snapshots")
    with op.batch_alter_table("regime_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_regime_runs_status"))

    op.drop_table("regime_runs")
    with op.batch_alter_table("regime_observations", schema=None) as batch_op:
        batch_op.drop_index("ix_regime_observation_asof")

    op.drop_table("regime_observations")
    op.drop_table("regime_config")
    op.drop_table("regime_access")
    op.drop_table("regime_transitions")
    op.drop_table("regime_source_state")
    op.drop_table("regime_raw_payloads")
    op.drop_table("regime_model_versions")
    with op.batch_alter_table("regime_licenses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_regime_licenses_source_id"))

    op.drop_table("regime_licenses")
    op.drop_table("regime_backtest_runs")
    # ### end Alembic commands ###
