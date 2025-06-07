"""Change Player.discord_id to String

Revision ID: 7ce14fdd3612
Revises: 0d1b1948d058
Create Date: 2025-06-07 17:40:36.138166

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ce14fdd3612'
down_revision: Union[str, None] = '0d1b1948d058'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('players', 'discord_id',
               existing_type=sa.Integer(),
               type_=sa.String(),
               nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('players', 'discord_id',
               existing_type=sa.String(),
               type_=sa.Integer(),
               nullable=True)
