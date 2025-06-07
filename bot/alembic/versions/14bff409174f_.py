"""empty message

Revision ID: 14bff409174f
Revises: 3ed41ecfc55e, b94e4733d12d
Create Date: 2025-06-07 00:41:40.874101

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '14bff409174f'
down_revision: Union[str, None] = ('3ed41ecfc55e', 'b94e4733d12d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
