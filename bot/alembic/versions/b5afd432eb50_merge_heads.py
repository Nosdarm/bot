"""merge heads

Revision ID: b5afd432eb50
Revises: 66eb704dd916, cb2f59e829fc, ebfcb0e24979
Create Date: 2025-06-22 17:59:54.306789

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5afd432eb50'
down_revision: Union[str, None] = ('66eb704dd916', 'cb2f59e829fc', 'ebfcb0e24979')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
