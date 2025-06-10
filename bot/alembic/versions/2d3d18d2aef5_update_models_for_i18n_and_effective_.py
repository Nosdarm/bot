"""update_models_for_i18n_and_effective_stats_attempt_3

Revision ID: 2d3d18d2aef5
Revises: a2122e3e0dbb
Create Date: 2025-06-10 17:25:43.476232

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d3d18d2aef5'
down_revision: Union[str, None] = 'a2122e3e0dbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
