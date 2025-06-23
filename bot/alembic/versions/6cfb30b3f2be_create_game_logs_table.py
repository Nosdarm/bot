"""Create game_logs table

Revision ID: 6cfb30b3f2be
Revises: d275002e4c9b
Create Date: 2025-06-23 16:26:26.777053

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6cfb30b3f2be'
down_revision: Union[str, None] = 'd275002e4c9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'game_logs',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('timestamp', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('guild_id', sa.Text(), sa.ForeignKey('guild_configs.guild_id', name='fk_game_logs_guild_id_guild_configs', ondelete='CASCADE'), nullable=False),
        sa.Column('player_id', sa.Text(), sa.ForeignKey('players.id', name='fk_game_logs_player_id_players'), nullable=True),
        sa.Column('party_id', sa.Text(), sa.ForeignKey('parties.id', name='fk_game_logs_party_id_parties'), nullable=True),
        sa.Column('location_id', sa.Text(), sa.ForeignKey('locations.id', name='fk_game_logs_location_id_locations'), nullable=True),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('description_key', sa.Text(), nullable=True),
        sa.Column('description_params_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('involved_entities_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='JSON array or object of involved entity IDs, e.g., {"characters": [], "npcs": []}'),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Flexible JSON field for additional structured data about the event'),
        sa.Column('channel_id', sa.Text(), nullable=True),
        sa.Column('source_entity_id', sa.Text(), nullable=True),
        sa.Column('source_entity_type', sa.Text(), nullable=True),
        sa.Column('target_entity_id', sa.Text(), nullable=True),
        sa.Column('target_entity_type', sa.Text(), nullable=True)
    )
    op.create_index(op.f('ix_game_logs_timestamp'), 'game_logs', ['timestamp'], unique=False)
    op.create_index(op.f('ix_game_logs_guild_id'), 'game_logs', ['guild_id'], unique=False)
    op.create_index(op.f('ix_game_logs_player_id'), 'game_logs', ['player_id'], unique=False)
    op.create_index(op.f('ix_game_logs_party_id'), 'game_logs', ['party_id'], unique=False)
    op.create_index(op.f('ix_game_logs_location_id'), 'game_logs', ['location_id'], unique=False)
    op.create_index(op.f('ix_game_logs_event_type'), 'game_logs', ['event_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_game_logs_event_type'), table_name='game_logs')
    op.drop_index(op.f('ix_game_logs_location_id'), table_name='game_logs')
    op.drop_index(op.f('ix_game_logs_party_id'), table_name='game_logs')
    op.drop_index(op.f('ix_game_logs_player_id'), table_name='game_logs')
    op.drop_index(op.f('ix_game_logs_guild_id'), table_name='game_logs')
    op.drop_index(op.f('ix_game_logs_timestamp'), table_name='game_logs')
    op.drop_table('game_logs')
