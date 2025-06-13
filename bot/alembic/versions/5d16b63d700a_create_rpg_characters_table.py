"""create_rpg_characters_table

Revision ID: 5d16b63d700a
Revises: 00d77338d2b8
Create Date: 2025-06-13 19:29:34.154096

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql # For UUID type

# revision identifiers, used by Alembic.
revision: str = '5d16b63d700a'
down_revision: Union[str, None] = '00d77338d2b8' # Ensure this is the correct previous revision ID
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'rpg_characters',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')), # Using server_default for UUID generation
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('class_name', sa.String(), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('health', sa.Integer(), nullable=False),
        sa.Column('mana', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False)
    )
    op.create_check_constraint('check_level_non_negative', 'rpg_characters', sa.text('level >= 0'))
    op.create_check_constraint('check_health_non_negative', 'rpg_characters', sa.text('health >= 0'))
    op.create_check_constraint('check_mana_non_negative', 'rpg_characters', sa.text('mana >= 0'))


def downgrade() -> None:
    op.drop_table('rpg_characters')
