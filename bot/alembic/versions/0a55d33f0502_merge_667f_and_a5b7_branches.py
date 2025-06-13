"""merge 667f and a5b7 branches

Revision ID: 0a55d33f0502
Revises: 667f91524537, a5b7c6d8e9f0
Create Date: 2025-06-13 17:18:35.049390

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a55d33f0502'
down_revision: Union[str, None] = ('667f91524537', 'a5b7c6d8e9f0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
