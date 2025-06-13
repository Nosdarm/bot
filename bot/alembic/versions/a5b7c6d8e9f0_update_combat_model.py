"""update_combat_model

Revision ID: a5b7c6d8e9f0
Revises: f4d6c5e7a8b9
Create Date: 2024-07-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql # For JSON type if needed

# revision identifiers, used by Alembic.
revision: str = 'a5b7c6d8e9f0'
down_revision: Union[str, None] = 'f4d6c5e7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Combat model updates ###
    # Note: Python-level default change for 'id' (lambda str(uuid.uuid4())) is not a schema change.

    # 1. participants: Change from nullable=True to nullable=False, default=[]
    # First, update existing NULL participants to an empty JSON array.
    op.execute("UPDATE combats SET participants = '[]'::jsonb WHERE participants IS NULL")
    # Then, alter the column to be NOT NULL and set a server default temporarily.
    op.alter_column('combats', 'participants',
               existing_type=sa.JSON(),
               nullable=False,
               server_default='[]')
    # Remove the server_default after constraint is applied if Python default is preferred for new inserts.
    op.alter_column('combats', 'participants', server_default=None)


    # 2. Add initial_positions column (nullable)
    op.add_column('combats', sa.Column('initial_positions', sa.JSON(), nullable=True))

    # 3. Add combat_rules_snapshot column (nullable)
    op.add_column('combats', sa.Column('combat_rules_snapshot', sa.JSON(), nullable=True))

    # 4. Replace is_active with status
    # Add the new status column, nullable temporarily to allow population.
    op.add_column('combats', sa.Column('status', sa.String(length=50), nullable=True))

    # Populate 'status' based on 'is_active'.
    # is_active=True -> 'active', is_active=False -> 'completed' (example), NULL -> 'pending'
    op.execute("UPDATE combats SET status = CASE "
               "WHEN is_active = TRUE THEN 'active' "
               "WHEN is_active = FALSE THEN 'completed' "
               "ELSE 'pending' END")

    # Now make 'status' non-nullable and set its final server default.
    op.alter_column('combats', 'status',
               existing_type=sa.String(length=50),
               nullable=False,
               server_default='pending')
    # The server_default 'pending' is intended to stay.

    # Create index on status
    op.create_index(op.f('ix_combats_status'), 'combats', ['status'], unique=False)

    # Drop the old is_active column
    op.drop_column('combats', 'is_active')


    # 5. Add turn_log_structured column (nullable, Python default is lambda: [])
    op.add_column('combats', sa.Column('turn_log_structured', sa.JSON(), nullable=True))
    # Optional: Update existing NULLs to '[]' for consistency if desired.
    # op.execute("UPDATE combats SET turn_log_structured = '[]'::jsonb WHERE turn_log_structured IS NULL")


def downgrade() -> None:
    # ### Combat model updates (reverse) ###

    # 5. Reverse turn_log_structured
    op.drop_column('combats', 'turn_log_structured')

    # 4. Reverse status to is_active
    # Add back is_active, nullable=True as it was (default=True in model implies nullable=True)
    op.add_column('combats', sa.Column('is_active', sa.Boolean(), nullable=True))

    # Populate is_active based on status
    # 'active' -> TRUE, others ('pending', 'completed', etc.) -> FALSE
    op.execute("UPDATE combats SET is_active = CASE WHEN status = 'active' THEN TRUE ELSE FALSE END")

    # Set server_default for is_active to True (original model had default=True)
    # This is applied if new rows are inserted via SQL without specifying is_active.
    # If the column is made non-nullable later, this default would be critical.
    # For a nullable boolean, it's less critical but matches original intent.
    op.alter_column('combats', 'is_active', server_default=sa.true())
    # Then remove it if the Python default is the primary one desired.
    op.alter_column('combats', 'is_active', server_default=None)


    op.drop_index(op.f('ix_combats_status'), table_name='combats')
    op.drop_column('combats', 'status')


    # 3. Reverse combat_rules_snapshot
    op.drop_column('combats', 'combat_rules_snapshot')

    # 2. Reverse initial_positions
    op.drop_column('combats', 'initial_positions')

    # 1. Reverse participants: Change from nullable=False back to nullable=True
    op.alter_column('combats', 'participants',
               existing_type=sa.JSON(),
               nullable=True)
    # Python-side default lambda:[] is removed with the model change.
    # No server_default was permanently set for 'participants' in upgrade, so none to remove here.
