"""add_pending_conflicts_table

Revision ID: 8034e74ff78f
Revises: bdb11d050621
Create Date: 2025-06-10 18:52:52.655355

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8034e74ff78f'
down_revision: Union[str, None] = 'bdb11d050621'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
