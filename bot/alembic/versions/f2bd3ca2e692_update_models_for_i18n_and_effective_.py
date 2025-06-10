"""update_models_for_i18n_and_effective_stats_attempt_4

Revision ID: f2bd3ca2e692
Revises: 2d3d18d2aef5
Create Date: 2025-06-10 17:26:25.749629

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2bd3ca2e692'
down_revision: Union[str, None] = '2d3d18d2aef5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
