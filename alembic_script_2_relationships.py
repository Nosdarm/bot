"""Create relationships table

Revision ID: script2_relationships_rev
Revises: script1_factions_rev
Create Date: YYYY-MM-DD HH:MM:SS.MSMSMS

"""
from alembic import op
import sqlalchemy as sa
import uuid

# revision identifiers, used by Alembic.
revision = 'script2_relationships_rev' # Replace with actual generated revision ID
down_revision = 'script1_factions_rev' # Points to the factions migration
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('relationships',
    sa.Column('id', sa.String(length=36), primary_key=True, default=lambda: str(uuid.uuid4())),
    sa.Column('guild_id', sa.String(length=255), nullable=False, index=True),
    sa.Column('entity1_id', sa.String(length=255), nullable=False, index=True),
    sa.Column('entity1_type', sa.String(length=50), nullable=False),
    sa.Column('entity2_id', sa.String(length=255), nullable=False, index=True),
    sa.Column('entity2_type', sa.String(length=50), nullable=False),
    sa.Column('relationship_type', sa.String(length=100), nullable=False, default='neutral', index=True),
    sa.Column('strength', sa.Float(), nullable=False, default=0.0),
    sa.Column('details_i18n', sa.Text(), nullable=True, default='{}'),
    sa.Column('timestamp', sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False)
    )
    # Add a composite unique constraint
    op.create_unique_constraint(
        'uq_relationship_entities_type',
        'relationships',
        ['guild_id', 'entity1_id', 'entity2_id', 'entity1_type', 'entity2_type', 'relationship_type']
    )

def downgrade():
    # For SQLite, dropping constraints might need table rebuild. For PostgreSQL/MySQL, this is fine.
    # op.drop_constraint('uq_relationship_entities_type', 'relationships', type_='unique') # Optional if table is dropped
    op.drop_table('relationships')
