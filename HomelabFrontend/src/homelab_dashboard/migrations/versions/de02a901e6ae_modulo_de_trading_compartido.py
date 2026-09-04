"""modulo de trading compartido

Crea las dos tablas del módulo de trading:

- `trading_access`: permiso por usuario, concedido por un admin. Su ausencia
  significa "sin acceso"; revocar es borrar la fila.
- `trading_bot_config`: configuración **compartida** por motor. No cuelga de
  `users` a propósito — es el único dato de la app que no pertenece a un
  usuario concreto, porque el bot es uno solo para todos los autorizados.

Nota sobre el `CHECK` de `mode`: admite un solo valor (`'paper'`). No es un
descuido, es la invariante que garantiza que el módulo nunca opere con dinero
real. Habilitar dinero real exigiría otra migración, que es justo la fricción
que se busca.

Los `DateTime` se declaran como `sa.DateTime()` y no como el `UtcDateTime` de
la app: es un `TypeDecorator` cuyo tipo real en SQLite ya es `DATETIME`, y una
migración no debe importar código de la aplicación (que puede cambiar o
desaparecer mientras la migración debe seguir siendo reproducible). Mismo
criterio que la migración inicial `2016beade187`.

Revision ID: de02a901e6ae
Revises: 2016beade187
Create Date: 2026-09-04 10:41:46.544154
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'de02a901e6ae'
down_revision: str | None = '2016beade187'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'trading_access',
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('level', sa.String(length=16), nullable=False),
        sa.Column('granted_by_user_id', sa.String(length=32), nullable=True),
        sa.Column('granted_by_email', sa.String(length=320), nullable=False),
        sa.Column('granted_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("level IN ('viewer', 'operator')", name='ck_level_valido'),
        sa.ForeignKeyConstraint(['granted_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_table(
        'trading_bot_config',
        sa.Column('bot_name', sa.String(length=32), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('mode', sa.String(length=16), server_default='paper', nullable=False),
        sa.Column('config_json', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('updated_by_user_id', sa.String(length=32), nullable=True),
        sa.Column('updated_by_email', sa.String(length=320), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("bot_name IN ('freqtrade', 'lumibot')", name='ck_bot_name_valido'),
        sa.CheckConstraint("mode IN ('paper')", name='ck_mode_valido'),
        sa.CheckConstraint('version > 0', name='ck_version_positiva'),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('bot_name'),
    )


def downgrade() -> None:
    op.drop_table('trading_bot_config')
    op.drop_table('trading_access')
