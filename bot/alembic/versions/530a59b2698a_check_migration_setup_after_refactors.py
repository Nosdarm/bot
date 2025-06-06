"""check_migration_setup_after_refactors

Revision ID: 530a59b2698a
Revises: a778bd28c00a
Create Date: 2025-06-06 00:21:53.253162

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '530a59b2698a'
down_revision: Union[str, None] = 'a778bd28c00a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
