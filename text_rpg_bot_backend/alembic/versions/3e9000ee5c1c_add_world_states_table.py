"""add_world_states_table

Revision ID: 3e9000ee5c1c
Revises: 07899561245e # Should point to the 'add_rule_configs_table' migration
Create Date: 2025-06-16 16:01:00.000000 # Placeholder, actual date will vary

"""
from alembic import op
import sqlalchemy as sa
# from sqlalchemy.dialects import postgresql # For JSONB if needed

# revision identifiers, used by Alembic.
revision = '3e9000ee5c1c'
down_revision = '07899561245e' # Points to the 'add_rule_configs_table' migration
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('world_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('state_data', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id', name='uq_world_states_guild_id') # Explicit name
    )
    op.create_index(op.f('ix_world_states_guild_id'), 'world_states', ['guild_id'], unique=True)
    # op.create_index(op.f('ix_world_states_id'), 'world_states', ['id'], unique=False) # PKs are usually indexed by default


def downgrade():
    # op.drop_index(op.f('ix_world_states_id'), table_name='world_states') # If created above
    op.drop_index(op.f('ix_world_states_guild_id'), table_name='world_states')
    op.drop_table('world_states')
