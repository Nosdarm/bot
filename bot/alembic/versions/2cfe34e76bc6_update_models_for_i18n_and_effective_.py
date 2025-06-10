"""update_models_for_i18n_and_effective_stats_attempt_6_no_pyc

Revision ID: 2cfe34e76bc6
Revises: 51f611e961bf
Create Date: 2025-06-10 17:27:39.497972

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2cfe34e76bc6'
down_revision: Union[str, None] = '51f611e961bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
