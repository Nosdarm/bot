"""Create factions table

Revision ID: 2c3d4e5f0a1b
Revises: 1b2c3d4e5f0a
Create Date: YYYY-MM-DD HH:MM:SS.MSMSMS # Placeholder, Alembic updates this

"""
from typing import Sequence, Union # Added for consistency
from alembic import op
import sqlalchemy as sa
import uuid # Kept from original loose script

# revision identifiers, used by Alembic.
revision: str = '2c3d4e5f0a1b'
down_revision: Union[str, None] = '1b2c3d4e5f0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None: # Added type hint for consistency
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


def downgrade() -> None: # Added type hint for consistency
    op.drop_table('factions')
