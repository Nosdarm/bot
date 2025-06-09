"""Add i18n and other fields to locations table

Revision ID: 20250608_add_i18n_fields_to_locations
Revises: fcaa9d8b2630
Create Date: 2025-06-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20250608_add_i18n_fields_to_locations'
down_revision: Union[str, None] = 'fcaa9d8b2630' # Assuming fcaa9d8b2630 is the latest prior migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name, column_name):
    """Checks if a column exists in a table."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = insp.get_columns(table_name)
    return any(c['name'] == column_name for c in columns)

def upgrade() -> None:
    """Upgrade schema."""
    columns_to_add = [
        {'name': 'details_i18n', 'type': postgresql.JSONB(astext_type=sa.Text()), 'attrs': {'nullable': True}},
        {'name': 'tags_i18n', 'type': postgresql.JSONB(astext_type=sa.Text()), 'attrs': {'nullable': True}},
        {'name': 'atmosphere_i18n', 'type': postgresql.JSONB(astext_type=sa.Text()), 'attrs': {'nullable': True}},
        {'name': 'features_i18n', 'type': postgresql.JSONB(astext_type=sa.Text()), 'attrs': {'nullable': True}},
        {'name': 'channel_id', 'type': sa.String(), 'attrs': {'nullable': True}},
        {'name': 'image_url', 'type': sa.String(), 'attrs': {'nullable': True}},
    ]

    for column_info in columns_to_add:
        if not column_exists('locations', column_info['name']):
            op.add_column('locations', sa.Column(column_info['name'], column_info['type'], **column_info['attrs']))
            print(f"Added column {column_info['name']} to locations table.")
        else:
            print(f"Column {column_info['name']} already exists in locations table. No action taken for this column.")


def downgrade() -> None:
    """Downgrade schema."""
    columns_to_drop = [
        'details_i18n',
        'tags_i18n',
        'atmosphere_i18n',
        'features_i18n',
        'channel_id',
        'image_url',
    ]

    for column_name in columns_to_drop:
        if column_exists('locations', column_name):
            # For SQLite compatibility in batch mode, but op.drop_column is generally fine for PG
            # with op.batch_alter_table('locations', schema=None) as batch_op:
            #     batch_op.drop_column(column_name)
            op.drop_column('locations', column_name)
            print(f"Dropped column {column_name} from locations table.")
        else:
            print(f"Column {column_name} does not exist in locations table. No action taken for this column.")
