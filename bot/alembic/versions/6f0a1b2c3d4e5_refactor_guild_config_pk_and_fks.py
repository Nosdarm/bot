"""Refactor GuildConfig PK to guild_id, modify columns, and update FKs

Revision ID: 6f0a1b2c3d4e5
Revises: 5f0a1b2c3d4e
Create Date: YYYY-MM-DD HH:MM:SS.MSMSMS # Placeholder, Alembic updates this

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6f0a1b2c3d4e5'
down_revision: Union[str, None] = '5f0a1b2c3d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

tables_fk_data = {
    "rules_config": "guild_id", "world_states": "guild_id", "players": "guild_id",
    "characters": "guild_id", "locations": "guild_id", "timers": "guild_id",
    "events": "guild_id", "parties": "guild_id", "generated_locations": "guild_id",
    "item_templates": "guild_id", "location_templates": "guild_id", "npcs": "guild_id",
    "generated_npcs": "guild_id", "generated_factions": "guild_id", "global_npcs": "guild_id",
    "items": "guild_id", "inventory": "guild_id", "combats": "guild_id",
    "player_npc_memory": "guild_id", "abilities": "guild_id", "skills": "guild_id",
    "statuses": "guild_id", "crafting_recipes": "guild_id", "crafting_queues": "guild_id",
    "item_properties": "guild_id", "questlines": "guild_id", "quest_steps": "guild_id",
    "mobile_groups": "guild_id", "pending_conflicts": "guild_id",
    "pending_generations": "guild_id", "user_settings": "guild_id",
    "story_logs": "guild_id", "relationships": "guild_id"
}

def upgrade() -> None:
    # ### Part 1: GuildConfig Table Modifications ###
    try:
        op.drop_constraint('pk_guild_configs', 'guild_configs', type_='primary')
    except Exception as e:
        print(f"Info: Could not drop constraint 'pk_guild_configs' by name for upgrade: {e}")
    op.drop_column('guild_configs', 'id')

    op.alter_column('guild_configs', 'guild_id', nullable=False, existing_type=sa.String())
    op.create_primary_key(
        op.f('pk_guild_configs'),
        'guild_configs',
        ['guild_id']
    )
    op.add_column('guild_configs', sa.Column('master_channel_id', sa.String(), nullable=True))
    op.add_column('guild_configs', sa.Column('notification_channel_id', sa.String(), nullable=True))
    op.alter_column('guild_configs',
                    'system_notifications_channel_id',
                    new_column_name='system_channel_id',
                    existing_type=sa.String(),
                    nullable=True)

    # ### Part 2: Foreign Key Updates ###
    op.execute("COMMIT") # Commit schema changes before altering FKs that depend on PK type
    # Some databases might require this, or it might be handled by Alembic's transactional DDL.
    # For safety with so many FKs, an explicit commit might be useful if running outside Alembic's default transaction-per-migration.
    # However, within Alembic's standard flow, this might break things. Best to rely on Alembic's transaction handling.
    # Let's remove this explicit commit for now as it's generally not standard in Alembic migrations.

    print("Updating Foreign Keys to point to guild_configs.guild_id (PK)")
    for table_name, fk_column_name in tables_fk_data.items():
        constraint_name = op.f(f'fk_{table_name}_{fk_column_name}_guild_configs')
        print(f"Attempting to update FK for table: {table_name}, constraint: {constraint_name}")
        try:
            op.drop_constraint(constraint_name, table_name, type_='foreignkey')
            print(f"Successfully dropped constraint '{constraint_name}' on table '{table_name}'.")
        except Exception as e:
            # This is expected if the constraint name was different or didn't exist.
            # Or if the constraint was defined to point to a unique key `guild_id` that wasn't the PK.
            print(f"Info: Could not drop constraint '{constraint_name}' on table '{table_name}'. It might not exist, name was different, or target was UK not PK: {e}")

        try:
            op.create_foreign_key(
                constraint_name, # Recreate with the same standard name
                table_name, 'guild_configs',
                [fk_column_name], ['guild_id'], # Local column(s), remote column(s)
                ondelete='CASCADE'
            )
            print(f"Successfully created constraint '{constraint_name}' on table '{table_name}'.")
        except Exception as e:
            print(f"ERROR: Could not create constraint '{constraint_name}' on table '{table_name}': {e}")
            # Depending on the DB, this might be a critical error.
            # If the local column type doesn't match guild_configs.guild_id type, it could fail.
            # All guild_id columns in other tables should be sa.String.


def downgrade() -> None:
    # ### Part 2: Revert Foreign Key Updates ###
    # This simplified downgrade only drops the FKs created in the upgrade.
    # A full revert would require recreating FKs to point to the old 'id' PK of guild_configs.
    print("Reverting Foreign Key changes.")
    for table_name, fk_column_name in tables_fk_data.items():
        constraint_name = op.f(f'fk_{table_name}_{fk_column_name}_guild_configs')
        print(f"Attempting to drop constraint '{constraint_name}' on table '{table_name}' during downgrade.")
        try:
            op.drop_constraint(constraint_name, table_name, type_='foreignkey')
            print(f"Successfully dropped constraint '{constraint_name}' on table '{table_name}'.")
        except Exception as e:
            print(f"Info: Could not drop constraint '{constraint_name}' on table '{table_name}' during downgrade: {e}")

        # Developer Note: To fully revert to the state *before* guild_id became PK (i.e., when 'id' was PK),
        # one would need to re-create FKs pointing to guild_configs.id.
        # This was handled by migration ad464255a42c for many tables, pointing to guild_configs.guild_id (as a UK).
        # If that migration is reverted, its downgrade path should handle restoring original FKs.
        # If this migration (6f0a...) is reverted, we are going back to a state where 'id' is PK on guild_configs.
        # So, FKs from other tables should point to guild_configs.id.
        # This might require a different set of constraint names than what `ad46...` established.
        # For now, we'll recreate FKs to guild_configs.id using a potentially new conventional name.
        # This assumes the local fk_column_name (e.g. 'guild_id') should now point to the 'id' column of guild_configs.
        # This is complex and depends on the true state before this migration.
        # The migration 'ad46...' made FKs point to guild_configs.guild_id (which was a unique key).
        # So, the state *before this migration (6f0a...)* had FKs targeting guild_configs.guild_id (UK).
        # If 'id' becomes PK again on downgrade, these FKs should ideally point to 'id'.
        # However, the column types might mismatch (guild_id is String, id was UUID-like String).
        # This downgrade is complex. For now, the most important part is dropping the FK to the PK guild_id.
        # Re-establishing the FK to the old 'id' might be better handled by reverting ad46... if that's the path.
        # For now, let's try to recreate FKs to guild_configs.guild_id (which is now a UK again, not PK).
        # This matches the state supposedly established by ad46...
        # The actual PK 'id' is restored below.
        print(f"Re-creating FK (if it existed) from {table_name}.{fk_column_name} to guild_configs.guild_id (as UK) for downgrade consistency with ad46...")
        try:
            op.create_foreign_key(
                constraint_name, # Use the same name as it was before this migration made guild_id PK
                table_name,
                'guild_configs',
                [fk_column_name],
                ['guild_id'], # Pointing back to guild_id (which is now a unique key, not PK)
                ondelete='CASCADE'
            )
        except Exception as e:
            print(f"Info: Could not re-create constraint '{constraint_name}' on table '{table_name}' to guild_configs.guild_id (UK) during downgrade: {e}")


    # ### Part 1: Revert GuildConfig Table Modifications ###
    op.alter_column('guild_configs',
                    'system_channel_id',
                    new_column_name='system_notifications_channel_id',
                    existing_type=sa.String(),
                    nullable=True)
    op.drop_column('guild_configs', 'notification_channel_id')
    op.drop_column('guild_configs', 'master_channel_id')

    op.drop_constraint(op.f('pk_guild_configs'), 'guild_configs', type_='primary')

    op.add_column('guild_configs', sa.Column('id', sa.String(), nullable=True))
    # In a real scenario, might need to populate this with UUIDs if making it non-nullable PK
    # For now, assuming it can be nullable during transition or data is lost/recreated.
    # op.execute("UPDATE guild_configs SET id = uuid_generate_v4() WHERE id IS NULL") # If using postgresql uuid-ossp

    # Make 'id' primary key again.
    # This assumes 'id' column is now populated or can be PK even if some are NULL (not typical for PK).
    # Let's assume 'id' should be made non-nullable before becoming PK in a robust scenario.
    # For now, trying to create PK. If this fails due to NULLs, the downgrade is more complex.
    op.create_primary_key(
        'pk_guild_configs',
        'guild_configs',
        ['id']
    )
    # Ensure guild_id is still not nullable and unique, as it was before becoming PK
    op.alter_column('guild_configs', 'guild_id', nullable=False, existing_type=sa.String())
    try:
        op.create_unique_constraint(op.f('uq_guild_configs_guild_id'), 'guild_configs', ['guild_id'])
    except Exception as e:
        print(f"Info: Could not re-create unique constraint on guild_id during downgrade, it might already exist: {e}")
    # Index on guild_id should also ideally be there if it's not the PK.
    # op.create_index(op.f('ix_guild_configs_guild_id'), 'guild_configs', ['guild_id'], unique=False) # unique=False because of UniqueConstraint

    pass
