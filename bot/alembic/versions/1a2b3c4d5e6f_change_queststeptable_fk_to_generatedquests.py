"""change_queststeptable_fk_to_generatedquests

Revision ID: 1a2b3c4d5e6f
Revises: f5d3a2b1c8e7
Create Date: YYYY-MM-DD HH:MM:SS.MS

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1a2b3c4d5e6f'
down_revision = 'f5d3a2b1c8e7'
branch_labels = None
depends_on = None

# Standard names for constraints and indexes (may vary if explicitly named in models)
old_fk_name = 'fk_quest_steps_quest_id_quests'
new_fk_name = 'fk_quest_steps_quest_id_generated_quests'
index_name = 'ix_quest_steps_quest_id' # Default index name for index=True

def upgrade():
    # Drop existing foreign key constraint and index
    # Need to ensure the old constraint name is correct. If SQLAlchemy auto-named it,
    # it might be different. For safety, one might inspect the DB or use a try-except.
    # However, Alembic's autogenerate usually finds these names.
    # We assume 'fk_quest_steps_quest_id_quests' or similar was the old convention.
    # If the index was created simply by index=True without explicit naming via FK,
    # its name would be 'ix_quest_steps_quest_id'.

    # Step 1: Drop the old index first if it exists and is not tied to the FK constraint itself
    # (some DBs drop index with FK, others don't). To be safe, drop explicitly.
    try:
        op.drop_index(index_name, table_name='quest_steps')
    except Exception as e:
        print(f"Could not drop old index {index_name} (it might not exist or be tied to FK): {e}")

    # Step 2: Drop the old foreign key constraint
    # The name 'fk_quest_steps_quest_id_quests' is an assumption based on common SQLAlchemy naming.
    # If this fails, it implies the auto-generated name was different or it was dropped with the index.
    try:
        op.drop_constraint(old_fk_name, 'quest_steps', type_='foreignkey')
    except Exception as e:
        print(f"Could not drop old FK constraint {old_fk_name} (it might not exist or name differs): {e}")
        # As a fallback, try to alter the column to remove the FK if name is unknown.
        # This is less clean and might not work universally or if the FK has a non-standard name.
        # For this exercise, we'll assume the named drop is the primary path.
        # A more robust script might inspect the table for existing FKs on the column.

    # Step 3: Create the new foreign key constraint to 'generated_quests'
    op.create_foreign_key(
        new_fk_name,
        'quest_steps', 'generated_quests',
        ['quest_id'], ['id'],
        ondelete='CASCADE'
    )

    # Step 4: Create the index for the new foreign key (if not automatically created by index=True on model)
    # The model still has index=True, so SQLAlchemy will expect an index.
    op.create_index(index_name, 'quest_steps', ['quest_id'], unique=False)

def downgrade():
    # Reverse operations:
    # Step 1: Drop the new index
    op.drop_index(index_name, table_name='quest_steps')

    # Step 2: Drop the new foreign key constraint
    op.drop_constraint(new_fk_name, 'quest_steps', type_='foreignkey')

    # Step 3: Recreate the old foreign key constraint to 'quests'
    op.create_foreign_key(
        old_fk_name,
        'quest_steps', 'quests',
        ['quest_id'], ['id'],
        ondelete='CASCADE'
    )

    # Step 4: Recreate the old index
    op.create_index(index_name, 'quest_steps', ['quest_id'], unique=False)
