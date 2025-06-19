"""Merge multiple heads

Revision ID: c386169cb68a
Revises: 1a2b3c4d5e6f, a3d433e5916c, XXXXXXXXXXXX
Create Date: 2025-06-19 10:16:59.886300

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c386169cb68a'
down_revision: Union[str, None] = ('1a2b3c4d5e6f', 'a3d433e5916c', 'XXXXXXXXXXXX')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
