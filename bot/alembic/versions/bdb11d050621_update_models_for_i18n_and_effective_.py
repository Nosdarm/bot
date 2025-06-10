"""update_models_for_i18n_and_effective_stats_attempt_3

Revision ID: bdb11d050621
Revises: 90debb549d6b
Create Date: 2025-06-10 17:30:07.223023

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bdb11d050621'
down_revision: Union[str, None] = '90debb549d6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
