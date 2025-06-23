"""Merge multiple heads into one

Revision ID: d9dbc4f4caa8
Revises: 6789a895c800, d275002e4c9b
Create Date: 2025-06-23 19:00:56.134664

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9dbc4f4caa8'
down_revision: Union[str, None] = ('6789a895c800', 'd275002e4c9b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
