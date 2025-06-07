"""merge cf11a92eac17 and ee9973a651da

Revision ID: b94e4733d12d
Revises: cf11a92eac17, ee9973a651da
Create Date: 2025-06-07 03:24:47.989722

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b94e4733d12d'
down_revision: Union[str, None] = ('cf11a92eac17', 'ee9973a651da')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
