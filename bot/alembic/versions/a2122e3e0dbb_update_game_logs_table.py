"""update_game_logs_table

Revision ID: a2122e3e0dbb
Revises: 27e8ef18f8f6
Create Date: 2025-06-09 18:47:42.301720

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func
from sqlalchemy.dialects import postgresql # For JSON and TIMESTAMP
import uuid


# revision identifiers, used by Alembic.
revision: str = 'a2122e3e0dbb'
down_revision: Union[str, None] = '27e8ef18f8f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop the old 'logs' table if it exists
    op.drop_table('logs', if_exists=True)

    # Create the new 'game_logs' table
    op.create_table(
        'game_logs',
        sa.Column('id', sa.String(), primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column('timestamp', sa.TIMESTAMP(timezone=True), server_default=func.now()),
        sa.Column('guild_id', sa.String(), nullable=False, index=True),
        sa.Column('player_id', sa.String(), sa.ForeignKey('players.id'), nullable=True),
        sa.Column('party_id', sa.String(), sa.ForeignKey('parties.id'), nullable=True),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('message_key', sa.String(), nullable=True),
        sa.Column('message_params', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('location_id', sa.String(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('involved_entities_ids', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('details', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('channel_id', sa.String(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop the 'game_logs' table
    op.drop_table('game_logs')

    # Optionally, recreate the old 'logs' table if it's desired for a full rollback
    op.create_table(
        'logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('placeholder', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
