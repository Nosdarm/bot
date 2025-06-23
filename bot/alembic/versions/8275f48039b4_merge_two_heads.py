"""Merge two heads

Revision ID: 8275f48039b4
Revises: 506f4e6c1756, b43c1b9235b3
Create Date: 2025-06-23 19:31:35.385726

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8275f48039b4'
down_revision: Union[str, None] = ('506f4e6c1756', 'b43c1b9235b3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
