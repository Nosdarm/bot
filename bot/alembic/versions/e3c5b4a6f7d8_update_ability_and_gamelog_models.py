"""update_ability_and_gamelog_models

Revision ID: e3c5b4a6f7d8
Revises: d2b4c3e5f6a7
Create Date: 2024-07-26 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql # For JSON type if needed for specific alterations

# revision identifiers, used by Alembic.
revision: str = 'e3c5b4a6f7d8'
down_revision: Union[str, None] = 'd2b4c3e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Ability model updates ###
    # The change to default for 'id' (lambda str(uuid.uuid4())) is a Python-side default
    # and does not require a schema change if the column type itself isn't changing
    # or if it wasn't previously database-generated in a way that needs removal.
    # Assuming 'id' was already a String PK and the default is applied by SQLAlchemy layer.

    # Change nullability for existing columns.
    # Using server_default='{}' for JSON columns being made non-nullable.
    # This ensures existing NULLs are updated, then the server_default is removed.

    op.alter_column('abilities', 'name_i18n',
               existing_type=sa.JSON(), # Using sa.JSON, assuming it maps to JSONB or appropriate type
               nullable=False,
               server_default='{}')
    op.alter_column('abilities', 'name_i18n', server_default=None)


    op.alter_column('abilities', 'description_i18n',
               existing_type=sa.JSON(),
               nullable=False,
               server_default='{}')
    op.alter_column('abilities', 'description_i18n', server_default=None)

    op.alter_column('abilities', 'effect_i18n',
               existing_type=sa.JSON(),
               nullable=False,
               server_default='{}')
    op.alter_column('abilities', 'effect_i18n', server_default=None)

    op.alter_column('abilities', 'type_i18n',
               existing_type=sa.JSON(),
               nullable=False,
               server_default='{}')
    op.alter_column('abilities', 'type_i18n', server_default=None)


    # ### GameLog model updates ###
    op.add_column('game_logs', sa.Column('description_i18n', sa.JSON(), nullable=True))
    op.add_column('game_logs', sa.Column('consequences_data', sa.JSON(), nullable=True))

    op.alter_column('game_logs', 'details',
               existing_type=sa.JSON(),
               nullable=True)


def downgrade() -> None:
    # ### GameLog model updates (reverse) ###
    # When making 'details' non-nullable again, provide a default for any potential NULLs.
    op.alter_column('game_logs', 'details',
               existing_type=sa.JSON(),
               nullable=False,
               server_default='{}')
    op.alter_column('game_logs', 'details', server_default=None)

    op.drop_column('game_logs', 'consequences_data')
    op.drop_column('game_logs', 'description_i18n')

    # ### Ability model updates (reverse) ###
    # Reverting columns to nullable=True
    op.alter_column('abilities', 'type_i18n',
               existing_type=sa.JSON(),
               nullable=True)
    op.alter_column('abilities', 'effect_i18n',
               existing_type=sa.JSON(),
               nullable=True)
    op.alter_column('abilities', 'description_i18n',
               existing_type=sa.JSON(),
               nullable=True)
    op.alter_column('abilities', 'name_i18n',
               existing_type=sa.JSON(),
               nullable=True)
    # Downgrading Python-level 'id' default change is not applicable to schema.

