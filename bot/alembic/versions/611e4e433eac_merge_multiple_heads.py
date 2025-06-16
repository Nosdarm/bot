"""Merge multiple heads

Revision ID: 611e4e433eac
Revises: 2d0ff37f17c5, ad82dab346db
Create Date: 2025-06-16 14:45:05.090437

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '611e4e433eac'
down_revision: Union[str, None] = ('2d0ff37f17c5', 'ad82dab346db')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
