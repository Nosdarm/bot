"""refine_quest_models

Revision ID: 69abc92bc432
Revises: b9da85bd5b9e # Points to add_pending_generations_table
Create Date: 2025-06-16 17:50:00.000000 # Placeholder

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '69abc92bc432'
down_revision = 'b9da85bd5b9e' # From add_pending_generations_table
branch_labels = None
depends_on = None


def upgrade():
    # ### Refine GeneratedQuest ###
    op.add_column('generated_quests', sa.Column('questline_id', sa.Integer(), nullable=True))
    op.create_foreign_key(op.f('fk_generated_quests_questline_id_questlines'), 'generated_quests', 'questlines', ['questline_id'], ['id'])
    op.create_index(op.f('ix_generated_quests_questline_id'), 'generated_quests', ['questline_id'], unique=False)

    op.add_column('generated_quests', sa.Column('assigning_npc_id', sa.Integer(), nullable=True))
    op.create_foreign_key(op.f('fk_generated_quests_assigning_npc_id_generated_npcs'), 'generated_quests', 'generated_npcs', ['assigning_npc_id'], ['id'])
    op.create_index(op.f('ix_generated_quests_assigning_npc_id'), 'generated_quests', ['assigning_npc_id'], unique=False)

    op.add_column('generated_quests', sa.Column('required_level', sa.Integer(), nullable=True, server_default='1'))
    op.add_column('generated_quests', sa.Column('template_status', sa.Text(), nullable=False, server_default='draft'))

    # ### Refine Questline ###
    op.add_column('questlines', sa.Column('starting_quest_static_id', sa.Text(), nullable=True))
    # Note: If 'starting_quest_id' (FK) existed from placeholder and needs removal, it would be:
    # op.drop_constraint('fk_name_if_any', 'questlines', type_='foreignkey')
    # op.drop_column('questlines', 'starting_quest_id')


    # ### Refine QuestStep ###
    op.add_column('quest_steps', sa.Column('goal_summary_i18n', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")))
    op.add_column('quest_steps', sa.Column('required_mechanics_placeholder_json', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")))
    op.add_column('quest_steps', sa.Column('consequences_placeholder_json', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")))
    # Ensure 'step_order' which had default=1 in model now has server_default if it didn't before
    # This might require an op.alter_column if it was created without server_default in the "phase2" migration.
    # For now, assuming the "phase2" migration handled server_default for existing columns where model default was set.
    # If not, it would be:
    # op.alter_column('quest_steps', 'step_order', server_default='1', existing_type=sa.Integer(), existing_nullable=False)


def downgrade():
    # ### Refine QuestStep ###
    op.drop_column('quest_steps', 'consequences_placeholder_json')
    op.drop_column('quest_steps', 'required_mechanics_placeholder_json')
    op.drop_column('quest_steps', 'goal_summary_i18n')
    # op.alter_column('quest_steps', 'step_order', server_default=None) # If server_default was added/changed

    # ### Refine Questline ###
    op.drop_column('questlines', 'starting_quest_static_id')
    # If 'starting_quest_id' FK was dropped, re-add it in downgrade:
    # op.add_column('questlines', sa.Column('starting_quest_id', sa.INTEGER(), autoincrement=False, nullable=True))
    # op.create_foreign_key('fk_name_if_any', 'questlines', 'generated_quests', ['starting_quest_id'], ['id'])


    # ### Refine GeneratedQuest ###
    op.drop_column('generated_quests', 'template_status')
    op.drop_column('generated_quests', 'required_level')

    op.drop_index(op.f('ix_generated_quests_assigning_npc_id'), table_name='generated_quests')
    op.drop_constraint(op.f('fk_generated_quests_assigning_npc_id_generated_npcs'), 'generated_quests', type_='foreignkey')
    op.drop_column('generated_quests', 'assigning_npc_id')

    op.drop_index(op.f('ix_generated_quests_questline_id'), table_name='generated_quests')
    op.drop_constraint(op.f('fk_generated_quests_questline_id_questlines'), 'generated_quests', type_='foreignkey')
    op.drop_column('generated_quests', 'questline_id')
