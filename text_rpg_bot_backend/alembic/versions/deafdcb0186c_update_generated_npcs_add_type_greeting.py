"""update_generated_npcs_add_type_greeting

Revision ID: deafdcb0186c
Revises: b9da85bd5b9e # Points to 'add_pending_generations_table'
Create Date: 2025-06-16 17:15:00.000000 # Placeholder

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'deafdcb0186c'
down_revision = 'b9da85bd5b9e' # Points to 'add_pending_generations_table'
branch_labels = None
depends_on = None


def upgrade():
    # Add npc_type column to generated_npcs table
    op.add_column('generated_npcs', sa.Column('npc_type', sa.Text(), nullable=True))

    # Add dialogue_greeting_i18n column to generated_npcs table
    op.add_column('generated_npcs', sa.Column('dialogue_greeting_i18n', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")))


def downgrade():
    op.drop_column('generated_npcs', 'dialogue_greeting_i18n')
    op.drop_column('generated_npcs', 'npc_type')
