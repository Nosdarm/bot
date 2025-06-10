"""update_models_for_i18n_and_effective_stats_attempt_2

Revision ID: 90debb549d6b
Revises: 2cfe34e76bc6
Create Date: 2025-06-10 17:29:14.190324

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90debb549d6b'
down_revision: Union[str, None] = '2cfe34e76bc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
