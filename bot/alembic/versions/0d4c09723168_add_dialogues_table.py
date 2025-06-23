"""add_dialogues_table

Revision ID: 0d4c09723168
Revises: b9cc85c9328c
Create Date: 2025-06-23 15:19:30.869562

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0d4c09723168'
down_revision: Union[str, None] = 'b9cc85c9328c' # Ensure this points to the previous migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('dialogues',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('template_id', sa.Text(), nullable=True),
        sa.Column('guild_id', sa.Text(), nullable=False),
        sa.Column('participants', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('channel_id', sa.Text(), nullable=True),
        sa.Column('current_stage_id', sa.Text(), nullable=True),
        sa.Column('state_variables', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('last_activity_game_time', sa.DOUBLE_PRECISION(), nullable=True),
        sa.Column('event_id', sa.Text(), nullable=True),
        sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
        sa.ForeignKeyConstraint(['guild_id'], ['guild_configs.guild_id'], name='fk_dialogues_guild_id_guild_configs', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dialogues_guild_id'), 'dialogues', ['guild_id'], unique=False)
    op.create_index(op.f('ix_dialogues_is_active'), 'dialogues', ['is_active'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_dialogues_is_active'), table_name='dialogues')
    op.drop_index(op.f('ix_dialogues_guild_id'), table_name='dialogues')
    op.drop_table('dialogues')
