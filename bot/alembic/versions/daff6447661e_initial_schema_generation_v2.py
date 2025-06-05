"""initial_schema_generation_v2

Revision ID: daff6447661e
Revises:
Create Date: 2025-06-05 19:43:29.727203

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'daff6447661e'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'players',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('discord_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('current_location_id', sa.String(), nullable=True),
        sa.Column('selected_language', sa.String(), nullable=True),
        sa.Column('xp', sa.Integer(), nullable=True),
        sa.Column('level', sa.Integer(), nullable=True),
        sa.Column('unspent_xp', sa.Integer(), nullable=True),
        sa.Column('gold', sa.Integer(), nullable=True),
        sa.Column('current_game_status', sa.String(), nullable=True),
        sa.Column('collected_actions_json', sa.JSON(), nullable=True),
        sa.Column('current_party_id', sa.String(), nullable=True),
        sa.Column('guild_id', sa.String(), nullable=False),
        sa.Column('stats', sa.JSON(), nullable=True),
        sa.Column('current_action', sa.String(), nullable=True),
        sa.Column('action_queue', sa.JSON(), nullable=True),
        sa.Column('state_variables', sa.JSON(), nullable=True),
        sa.Column('hp', sa.Integer(), nullable=True),
        sa.Column('max_health', sa.Integer(), nullable=True),
        sa.Column('is_alive', sa.Boolean(), nullable=True),
        sa.Column('status_effects', sa.JSON(), nullable=True),
        sa.Column('race', sa.String(), nullable=True),
        sa.Column('mp', sa.Integer(), nullable=True),
        sa.Column('attack', sa.Integer(), nullable=True),
        sa.Column('defense', sa.Integer(), nullable=True),
        sa.Column('skills_data_json', sa.JSON(), nullable=True),
        sa.Column('abilities_data_json', sa.JSON(), nullable=True),
        sa.Column('spells_data_json', sa.JSON(), nullable=True),
        sa.Column('character_class', sa.String(), nullable=True),
        sa.Column('flags_json', sa.JSON(), nullable=True),
        sa.Column('active_quests', sa.JSON(), nullable=True),
        sa.Column('known_spells', sa.JSON(), nullable=True),
        sa.Column('spell_cooldowns', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['current_location_id'], ['locations.id'], ),
        sa.ForeignKeyConstraint(['current_party_id'], ['parties.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('players')
