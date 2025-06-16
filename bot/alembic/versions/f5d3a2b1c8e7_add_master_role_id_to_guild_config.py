"""add master_role_id to guild_config

Revision ID: f5d3a2b1c8e7
Revises: d7c14313c370
Create Date: YYYY-MM-DD HH:MM:SS.MS

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f5d3a2b1c8e7'
down_revision = 'd7c14313c370' # Assuming this is a recent relevant head
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('guild_configs',
        sa.Column('master_role_id', sa.String(), nullable=True)
    )
    op.create_index(op.f('ix_guild_configs_master_role_id'), 'guild_configs', ['master_role_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_guild_configs_master_role_id'), table_name='guild_configs')
    op.drop_column('guild_configs', 'master_role_id')
