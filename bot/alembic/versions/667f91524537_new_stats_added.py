"""new stats added

Revision ID: 667f91524537
Revises: a763bbe776c0
Create Date: 2025-06-12 04:30:07.423666

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '667f91524537'
down_revision: Union[str, None] = 'a763bbe776c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
