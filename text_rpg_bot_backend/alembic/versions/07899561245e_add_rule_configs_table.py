"""add_rule_configs_table

Revision ID: 07899561245e
Revises: 9292c5fb0a93 # Should point to the 'initial_setup' migration
Create Date: 2025-06-16 15:55:00.000000 # Placeholder, actual date will vary

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql # For JSONB if needed, or sa.JSON

# revision identifiers, used by Alembic.
revision = '07899561245e'
down_revision = '9292c5fb0a93' # Points to the previous 'initial_setup' migration
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('rule_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('rules', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")), # Default to empty JSON object
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id', name='uq_rule_configs_guild_id') # Explicit name for constraint
    )
    # Index on guild_id is created due to UniqueConstraint with a name,
    # or if unique=True was on the Column directly.
    # For clarity or specific naming, an explicit index can be created:
    op.create_index(op.f('ix_rule_configs_guild_id'), 'rule_configs', ['guild_id'], unique=True)
    # Primary key usually gets an index automatically, but explicit index on id can also be added if needed for query patterns.
    # op.create_index(op.f('ix_rule_configs_id'), 'rule_configs', ['id'], unique=False) # Not strictly necessary for PK


def downgrade():
    op.drop_index(op.f('ix_rule_configs_guild_id'), table_name='rule_configs')
    # op.drop_index(op.f('ix_rule_configs_id'), table_name='rule_configs') # If created above
    op.drop_table('rule_configs')
