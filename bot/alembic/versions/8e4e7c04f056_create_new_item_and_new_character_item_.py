"""create_new_item_and_new_character_item_tables_attempt2

Revision ID: 8e4e7c04f056
Revises: 5d16b63d700a
Create Date: 2025-06-13 19:49:00.152441

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql # For JSONB

# revision identifiers, used by Alembic.
revision: str = '8e4e7c04f056'
down_revision: Union[str, None] = '5d16b63d700a' # Points to the migration before RPGCharacter was created, adjust if needed
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('new_items',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')), # Assuming gen_random_uuid for server-side UUID
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('item_type', sa.String(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint('name', name='uq_new_item_name')
    )

    op.create_table('new_character_items',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('character_id', sa.String(), nullable=False),
        sa.Column('item_id', sa.UUID(as_uuid=True), nullable=False),
        sa.Column('quantity', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], name='fk_new_character_items_character_id'),
        sa.ForeignKeyConstraint(['item_id'], ['new_items.id'], name='fk_new_character_items_item_id'),
        sa.CheckConstraint('quantity > 0', name='check_new_char_item_quantity_positive'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_new_character_items_character_id'), 'new_character_items', ['character_id'], unique=False)
    op.create_index(op.f('ix_new_character_items_item_id'), 'new_character_items', ['item_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_new_character_items_item_id'), table_name='new_character_items')
    op.drop_index(op.f('ix_new_character_items_character_id'), table_name='new_character_items')
    op.drop_table('new_character_items')
    op.drop_table('new_items')
