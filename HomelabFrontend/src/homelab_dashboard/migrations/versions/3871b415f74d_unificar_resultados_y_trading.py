"""unificar resultados y trading

Revision ID: 3871b415f74d
Revises: ddf944225582, de02a901e6ae
Create Date: 2026-09-07 12:56:23.550484
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "3871b415f74d"
down_revision: tuple[str, str] = ("ddf944225582", "de02a901e6ae")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
