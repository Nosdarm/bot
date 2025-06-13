"""update_location_model

Revision ID: f4d6c5e7a8b9
Revises: e3c5b4a6f7d8
Create Date: 2024-07-26 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql # For JSON type if needed

# revision identifiers, used by Alembic.
revision: str = 'f4d6c5e7a8b9'
down_revision: Union[str, None] = 'e3c5b4a6f7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Location model updates ###

    # Change nullability for name_i18n
    op.alter_column('locations', 'name_i18n',
               existing_type=sa.JSON(),
               nullable=False,
               server_default='{}') # Default for existing rows
    op.alter_column('locations', 'name_i18n', server_default=None)

    # Change nullability for descriptions_i18n
    op.alter_column('locations', 'descriptions_i18n',
               existing_type=sa.JSON(),
               nullable=False,
               server_default='{}') # Default for existing rows
    op.alter_column('locations', 'descriptions_i18n', server_default=None)

    # Add type_i18n column (non-nullable)
    op.add_column('locations', sa.Column('type_i18n', sa.JSON(), nullable=False, server_default='{}'))
    op.alter_column('locations', 'type_i18n', server_default=None)

    # Add coordinates column (nullable)
    op.add_column('locations', sa.Column('coordinates', sa.JSON(), nullable=True))

    # Add npc_ids column (nullable, Python-side default is lambda: [])
    # DB schema sees it as nullable JSON. No server_default needed for adding a nullable column.
    op.add_column('locations', sa.Column('npc_ids', sa.JSON(), nullable=True))
    # Optional: If you want to ensure existing rows get '[]' instead of NULL:
    # op.execute("UPDATE locations SET npc_ids = '[]'::jsonb WHERE npc_ids IS NULL")


    # Add event_triggers column (nullable, Python-side default is lambda: [])
    op.add_column('locations', sa.Column('event_triggers', sa.JSON(), nullable=True))
    # Optional: If you want to ensure existing rows get '[]' instead of NULL:
    # op.execute("UPDATE locations SET event_triggers = '[]'::jsonb WHERE event_triggers IS NULL")


def downgrade() -> None:
    # ### Location model updates (reverse) ###

    op.drop_column('locations', 'event_triggers')
    op.drop_column('locations', 'npc_ids')
    op.drop_column('locations', 'coordinates')
    op.drop_column('locations', 'type_i18n')

    # Reverting descriptions_i18n to nullable=True
    op.alter_column('locations', 'descriptions_i18n',
               existing_type=sa.JSON(),
               nullable=True)

    # Reverting name_i18n to nullable=True
    op.alter_column('locations', 'name_i18n',
               existing_type=sa.JSON(),
               nullable=True)

    # Note: Python-side default change for 'id' (adding lambda str(uuid.uuid4()))
    # is not reverted in schema as it's a Python-level default.
    # The column itself was likely already PK and string.

