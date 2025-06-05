"""test_postgres_setup

Revision ID: a778bd28c00a
Revises: daff6447661e
Create Date: 2025-06-05 23:39:24.942103

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a778bd28c00a'
down_revision: Union[str, None] = 'daff6447661e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
