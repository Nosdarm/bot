"""test_detection2

Revision ID: 6789a895c800
Revises: 96aa5aef75fb
Create Date: 2025-06-23 18:36:35.363451

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6789a895c800'
down_revision: Union[str, None] = '96aa5aef75fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
