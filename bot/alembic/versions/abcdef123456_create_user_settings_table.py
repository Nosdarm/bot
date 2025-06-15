"""create_user_settings_table

Revision ID: abcdef123456
Revises: dbe9815c6502
Create Date: 2024-03-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abcdef123456'
down_revision: Union[str, None] = 'dbe9815c6502'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('user_settings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('guild_id', sa.String(), nullable=False),
        sa.Column('language_code', sa.String(length=10), nullable=True),
        sa.Column('timezone', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['players.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'guild_id', name='uq_user_guild_settings')
    )
    op.create_index(op.f('ix_user_settings_guild_id'), 'user_settings', ['guild_id'], unique=False)
    op.create_index('idx_user_settings_user_guild', 'user_settings', ['user_id', 'guild_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_user_settings_user_guild', table_name='user_settings')
    op.drop_index(op.f('ix_user_settings_guild_id'), table_name='user_settings')
    op.drop_table('user_settings')
