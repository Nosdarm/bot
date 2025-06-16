"""add_pending_generations_table

Revision ID: b9da85bd5b9e
Revises: 346e447a45cc # Points to 'add_phase2_placeholder_models'
Create Date: 2025-06-16 17:10:00.000000 # Placeholder

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b9da85bd5b9e'
down_revision = '346e447a45cc' # Correct: points to the phase 2 placeholder models migration
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('pending_generations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('generation_type', sa.Text(), nullable=False),
        sa.Column('context_json', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('raw_ai_prompt', sa.Text(), nullable=True),
        sa.Column('raw_ai_response', sa.Text(), nullable=True),
        sa.Column('parsed_data_json', sa.JSON(), nullable=True), # Default is NULL
        sa.Column('validation_errors_json', sa.JSON(), nullable=True), # Default is NULL
        sa.Column('validation_warnings_json', sa.JSON(), nullable=True), # Default is NULL
        sa.Column('status', sa.Text(), nullable=False, server_default='pending_api_call'),
        sa.Column('requested_by_discord_id', sa.BigInteger(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_pending_generations'))
    )
    op.create_index(op.f('ix_pending_generations_id'), 'pending_generations', ['id'], unique=False)
    op.create_index(op.f('ix_pending_generations_guild_id'), 'pending_generations', ['guild_id'], unique=False)
    op.create_index(op.f('ix_pending_generations_status'), 'pending_generations', ['status'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_pending_generations_status'), table_name='pending_generations')
    op.drop_index(op.f('ix_pending_generations_guild_id'), table_name='pending_generations')
    op.drop_index(op.f('ix_pending_generations_id'), table_name='pending_generations')
    op.drop_table('pending_generations')
