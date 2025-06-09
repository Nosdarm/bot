"""merge_divergent_heads

Revision ID: 27e8ef18f8f6
Revises: 20250608_add_i18n_fields_to_locations, d2f7ee4feccd
Create Date: 2025-06-09 18:47:31.564079

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '27e8ef18f8f6'
down_revision: Union[str, None] = ('20250608_add_i18n_fields_to_locations', 'd2f7ee4feccd')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
