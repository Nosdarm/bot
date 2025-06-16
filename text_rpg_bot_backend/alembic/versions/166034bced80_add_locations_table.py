"""add_locations_table

Revision ID: 166034bced80
Revises: 3e9000ee5c1c # Should point to the 'add_world_states_table' migration
Create Date: 2025-06-16 16:43:00.000000 # Placeholder, actual date will vary

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql # For JSONB if needed, or sa.JSON

# revision identifiers, used by Alembic.
revision = '166034bced80'
down_revision = '3e9000ee5c1c' # Points to the 'add_world_states_table' migration
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('locations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('static_id', sa.Text(), nullable=True),
        sa.Column('name_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('descriptions_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('type', sa.Text(), nullable=True),
        sa.Column('coordinates_json', sa.JSON(), nullable=True), # Default is None/NULL
        sa.Column('neighbor_locations_json', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.Column('generated_details_json', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.Column('ai_metadata_json', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id', 'static_id', name='_guild_static_id_uc')
    )
    op.create_index(op.f('ix_locations_id'), 'locations', ['id'], unique=False) # Standard practice for PK index
    op.create_index(op.f('ix_locations_guild_id'), 'locations', ['guild_id'], unique=False)
    op.create_index(op.f('ix_locations_static_id'), 'locations', ['static_id'], unique=False) # Index for static_id lookups


def downgrade():
    op.drop_index(op.f('ix_locations_static_id'), table_name='locations')
    op.drop_index(op.f('ix_locations_guild_id'), table_name='locations')
    op.drop_index(op.f('ix_locations_id'), table_name='locations')
    op.drop_table('locations')
