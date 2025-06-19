"""Placeholder for missing revision 2d0ff37f17c5.
Original schema changes are lost.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2d0ff37f17c5'
# The down_revision below will be set to the parent of ad82dab346db
down_revision: Union[str, None] = '5cd9625c06db' # THIS WAS REPLACED
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Schema changes from the original missing file are lost.
    pass


def downgrade() -> None:
    # Schema changes from the original missing file are lost.
    pass
