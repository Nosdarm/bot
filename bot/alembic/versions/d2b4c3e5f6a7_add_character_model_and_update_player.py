"""add_character_model_and_update_player

Revision ID: d2b4c3e5f6a7
Revises: c1a3b2d4e5f6
Create Date: 2024-07-26 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd2b4c3e5f6a7'
down_revision: Union[str, None] = 'c1a3b2d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Player model updates ###
    op.add_column('players', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.alter_column('players', 'is_active', server_default=None)

    op.create_index(op.f('ix_players_is_active'), 'players', ['is_active'], unique=False)
    op.create_unique_constraint('uq_player_discord_guild', 'players', ['discord_id', 'guild_id'])

    # ### New Character table ###
    op.create_table('characters',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('player_id', sa.String(), nullable=False),
        sa.Column('guild_id', sa.String(), nullable=False),
        sa.Column('name_i18n', sa.JSON(), nullable=False),
        sa.Column('class_i18n', sa.JSON(), nullable=True),
        sa.Column('description_i18n', sa.JSON(), nullable=True),
        sa.Column('level', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('xp', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('stats', sa.JSON(), nullable=True),
        sa.Column('current_hp', sa.Float(), nullable=True),
        sa.Column('max_hp', sa.Float(), nullable=True),
        sa.Column('abilities', sa.JSON(), nullable=True),
        sa.Column('inventory', sa.JSON(), nullable=True),
        sa.Column('npc_relationships', sa.JSON(), nullable=True),
        sa.Column('is_active_char', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], name='fk_character_player_id')
    )
    op.create_index(op.f('ix_characters_player_id'), 'characters', ['player_id'], unique=False)
    op.create_index(op.f('ix_characters_guild_id'), 'characters', ['guild_id'], unique=False)
    op.create_index(op.f('ix_characters_is_active_char'), 'characters', ['is_active_char'], unique=False)
    op.create_index('idx_character_guild_player', 'characters', ['guild_id', 'player_id'], unique=False)

    # Remove server_default for columns where it was temporarily set for creation
    op.alter_column('characters', 'level', server_default=None)
    op.alter_column('characters', 'xp', server_default=None)
    op.alter_column('characters', 'is_active_char', server_default=None)


def downgrade() -> None:
    # ### New Character table ###
    op.drop_index('idx_character_guild_player', table_name='characters')
    op.drop_index(op.f('ix_characters_is_active_char'), table_name='characters')
    op.drop_index(op.f('ix_characters_guild_id'), table_name='characters')
    op.drop_index(op.f('ix_characters_player_id'), table_name='characters')
    op.drop_table('characters')

    # ### Player model updates ###
    op.drop_constraint('uq_player_discord_guild', 'players', type_='unique')
    op.drop_index(op.f('ix_players_is_active'), table_name='players')
    op.drop_column('players', 'is_active')
