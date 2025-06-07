"""merge divergent branches

Revision ID: 3ed41ecfc55e
Revises: 3f16a82ee39a, fcaa9d8b2630
Create Date: 2025-06-07 00:31:59.807849

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3ed41ecfc55e'
down_revision: Union[str, None] = ('3f16a82ee39a', 'fcaa9d8b2630')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
