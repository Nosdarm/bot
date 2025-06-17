"""add_points_of_interest_to_locations

Revision ID: a3d433e5916c
Revises:
Create Date: 2025-06-17 08:10:40.419350

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3d433e5916c'
down_revision: Union[str, None] = None # Set to None as this should be the first migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('locations', sa.Column('points_of_interest_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="List of Points of Interest objects/dictionaries"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('locations', 'points_of_interest_json')
