"""add_global_entities_and_updates

Revision ID: 2d0ff37f17c5
Revises: 5cd9625c06db
Create Date: 2025-06-16 10:51:35.333678

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d0ff37f17c5'
down_revision: Union[str, None] = '5cd9625c06db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
