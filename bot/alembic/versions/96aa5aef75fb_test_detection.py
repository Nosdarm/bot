"""test_detection

Revision ID: 96aa5aef75fb
Revises: 0d4c09723168
Create Date: 2025-06-23 18:35:29.873220

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '96aa5aef75fb'
down_revision: Union[str, None] = '0d4c09723168'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
