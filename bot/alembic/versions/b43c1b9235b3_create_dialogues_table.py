"""Create dialogues table

Revision ID: b43c1b9235b3
Revises: 6cfb30b3f2be
Create Date: 2025-06-23 16:27:10.688845

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b43c1b9235b3'
down_revision: Union[str, None] = '6cfb30b3f2be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'dialogues',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('template_id', sa.Text(), nullable=True),
        sa.Column('guild_id', sa.Text(), sa.ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False),
        sa.Column('participants', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('channel_id', sa.Text(), nullable=True),
        sa.Column('current_stage_id', sa.Text(), nullable=True),
        sa.Column('state_variables', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('last_activity_game_time', sa.DOUBLE_PRECISION(), nullable=True),
        sa.Column('event_id', sa.Text(), nullable=True),
        sa.Column('is_active', sa.BOOLEAN(), default=True, nullable=False)
    )
    op.create_index(op.f('ix_dialogues_guild_id'), 'dialogues', ['guild_id'], unique=False)
    op.create_index(op.f('ix_dialogues_is_active'), 'dialogues', ['is_active'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_dialogues_is_active'), table_name='dialogues')
    op.drop_index(op.f('ix_dialogues_guild_id'), table_name='dialogues')
    op.drop_table('dialogues')
