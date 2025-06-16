"""initial_setup

Revision ID: 9292c5fb0a93
Revises:
Create Date: 2025-06-16 15:52:00.000000 # Placeholder, actual date will vary

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9292c5fb0a93'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('guild_configs', # Changed from guild_config to guild_configs to match model
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('master_channel_id', sa.BigInteger(), nullable=True),
        sa.Column('system_channel_id', sa.BigInteger(), nullable=True),
        sa.Column('notification_channel_id', sa.BigInteger(), nullable=True),
        sa.Column('bot_language', sa.String(length=2), server_default='en', nullable=False), # model had default='en', nullable=False
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id', name='uq_guild_configs_guild_id') # Explicit name for unique constraint
    )
    # Index on guild_id is implicitly created by unique=True on Column or UniqueConstraint.
    # However, if explicit separate index is desired:
    op.create_index(op.f('ix_guild_configs_guild_id'), 'guild_configs', ['guild_id'], unique=True)


    op.create_table('players', # Changed from player to players to match model
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('discord_id', sa.BigInteger(), nullable=False),
        sa.Column('selected_language', sa.String(length=2), server_default='en', nullable=False), # model had default='en', nullable=False
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id', 'discord_id', name='_guild_user_uc')
    )
    op.create_index(op.f('ix_players_guild_id'), 'players', ['guild_id'], unique=False)
    op.create_index(op.f('ix_players_discord_id'), 'players', ['discord_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_players_discord_id'), table_name='players')
    op.drop_index(op.f('ix_players_guild_id'), table_name='players')
    op.drop_table('players')

    op.drop_index(op.f('ix_guild_configs_guild_id'), table_name='guild_configs')
    op.drop_table('guild_configs')
