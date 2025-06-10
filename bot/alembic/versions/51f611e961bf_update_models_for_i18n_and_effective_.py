"""update_models_for_i18n_and_effective_stats_attempt_5_except

Revision ID: 51f611e961bf
Revises: f2bd3ca2e692
Create Date: 2025-06-10 17:26:52.192809

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '51f611e961bf'
down_revision: Union[str, None] = 'f2bd3ca2e692'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
