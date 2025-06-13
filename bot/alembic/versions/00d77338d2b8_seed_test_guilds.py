"""seed_test_guilds

Revision ID: 00d77338d2b8
Revises: 0a55d33f0502
Create Date: 2025-06-13 17:18:40.185745

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00d77338d2b8'
down_revision: Union[str, None] = '0a55d33f0502'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Define the table structure for RulesConfig for use in bulk_insert
    rules_config_table = sa.table('rules_config',
        sa.column('guild_id', sa.String),
        sa.column('config_data', sa.JSON)
    )

    op.bulk_insert(rules_config_table, [
        {'guild_id': 'test_guild_001', 'config_data': {"default_language": "en", "command_prefixes": ["!"]}},
        {'guild_id': 'test_guild_002', 'config_data': {"default_language": "fr", "command_prefixes": ["%"]}},
        {'guild_id': 'test_guild_003', 'config_data': {"default_language": "es", "command_prefixes": ["$"]}}
    ])


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM rules_config WHERE guild_id IN ('test_guild_001', 'test_guild_002', 'test_guild_003')")
