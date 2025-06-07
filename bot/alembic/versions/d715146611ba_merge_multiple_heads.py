"""merge multiple heads

Revision ID: d715146611ba
Revises: 3f16a82ee39a, fcaa9d8b2630
Create Date: 2025-06-07 03:00:16.951585

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd715146611ba'
down_revision: Union[str, None] = ('3f16a82ee39a', 'fcaa9d8b2630')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
