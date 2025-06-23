"""Add description column to rules_config

Revision ID: d275002e4c9b
Revises: 0d4c09723168
Create Date: 2025-06-23 15:58:21.321550

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd275002e4c9b'
down_revision: Union[str, None] = '0d4c09723168'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('rules_config', sa.Column('description', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('rules_config', 'description')
