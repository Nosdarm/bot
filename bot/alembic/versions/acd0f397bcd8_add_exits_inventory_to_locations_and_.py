"""add_exits_inventory_to_locations_and_create_timers_table

Revision ID: acd0f397bcd8
Revises: 7d887g92h0f2
Create Date: 2025-06-06 22:57:34.232026

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
# from sqlalchemy.dialects import postgresql # Not used as existing migrations use sa.JSON

# revision identifiers, used by Alembic.
revision: str = 'acd0f397bcd8'
down_revision: Union[str, None] = '7d887g92h0f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add 'exits' and 'inventory' columns to 'locations' table
    op.add_column('locations', sa.Column('exits', sa.JSON(), nullable=True))
    op.add_column('locations', sa.Column('inventory', sa.JSON(), nullable=True))

    # Create 'timers' table
    op.create_table('timers',
                    sa.Column('id', sa.String(), nullable=False),
                    sa.Column('guild_id', sa.String(), nullable=False),
                    sa.Column('type', sa.String(), nullable=False),
                    sa.Column('ends_at', sa.Float(), nullable=False),
                    sa.Column('callback_data', sa.JSON(), nullable=True),
                    sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
                    sa.PrimaryKeyConstraint('id')
                    )
    op.create_index(op.f('ix_timers_guild_id'), 'timers', ['guild_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index from 'timers' table
    op.drop_index(op.f('ix_timers_guild_id'), table_name='timers')

    # Drop 'timers' table
    op.drop_table('timers')

    # Remove 'inventory' and 'exits' columns from 'locations' table
    op.drop_column('locations', 'inventory')
    op.drop_column('locations', 'exits')
