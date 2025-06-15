"""Create factions table

Revision ID: script1_factions_rev
Revises: <LATEST_PHASE7_REVISION_ID>
Create Date: YYYY-MM-DD HH:MM:SS.MSMSMS

"""
from alembic import op
import sqlalchemy as sa
import uuid

# revision identifiers, used by Alembic.
revision = 'script1_factions_rev' # Replace with actual generated revision ID
down_revision = '<LATEST_PHASE7_REVISION_ID>' # Replace with the actual down_revision ID
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('factions',
    sa.Column('id', sa.String(length=36), primary_key=True, default=lambda: str(uuid.uuid4())),
    sa.Column('guild_id', sa.String(length=255), nullable=False, index=True),
    sa.Column('name_i18n', sa.Text(), nullable=False),
    sa.Column('description_i18n', sa.Text(), nullable=True),
    sa.Column('leader_id', sa.String(length=255), nullable=True),
    sa.Column('alignment', sa.String(length=50), nullable=True),
    sa.Column('member_ids', sa.Text(), nullable=True, default='[]'),
    sa.Column('state_variables', sa.Text(), nullable=True, default='{}'),
    sa.Column('timestamp', sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False)
    )


def downgrade():
    op.drop_table('factions')
