"""add_phase2_placeholder_models

Revision ID: 346e447a45cc
Revises: 166034bced80 # Points to 'add_locations_table'
Create Date: 2025-06-16 16:57:30.000000 # Placeholder

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '346e447a45cc'
down_revision = '37b8a174fa4c' # Corrected: Points to 'update_players_add_parties_table'
branch_labels = None
depends_on = None


def upgrade():
    # ### GeneratedNpc ###
    op.create_table('generated_npcs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=True),
        sa.Column('static_id', sa.Text(), nullable=True),
        sa.Column('name_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('description_i18n', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_generated_npcs')),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_generated_npcs_location_id_locations')),
        sa.UniqueConstraint('guild_id', 'static_id', name='_npc_guild_static_id_uc')
    )
    op.create_index(op.f('ix_generated_npcs_guild_id'), 'generated_npcs', ['guild_id'], unique=False)
    op.create_index(op.f('ix_generated_npcs_location_id'), 'generated_npcs', ['location_id'], unique=False)
    op.create_index(op.f('ix_generated_npcs_static_id'), 'generated_npcs', ['static_id'], unique=False)
    op.create_index(op.f('ix_generated_npcs_id'), 'generated_npcs', ['id'], unique=False)

    # ### GeneratedFaction ###
    op.create_table('generated_factions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('static_id', sa.Text(), nullable=True),
        sa.Column('name_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('description_i18n', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.Column('ideology_i18n', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_generated_factions')),
        sa.UniqueConstraint('guild_id', 'static_id', name='_faction_guild_static_id_uc')
    )
    op.create_index(op.f('ix_generated_factions_guild_id'), 'generated_factions', ['guild_id'], unique=False)
    op.create_index(op.f('ix_generated_factions_static_id'), 'generated_factions', ['static_id'], unique=False)
    op.create_index(op.f('ix_generated_factions_id'), 'generated_factions', ['id'], unique=False)

    # ### GeneratedQuest ###
    op.create_table('generated_quests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('static_id', sa.Text(), nullable=True),
        sa.Column('title_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('description_i18n', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_generated_quests')),
        sa.UniqueConstraint('guild_id', 'static_id', name='_quest_guild_static_id_uc')
    )
    op.create_index(op.f('ix_generated_quests_guild_id'), 'generated_quests', ['guild_id'], unique=False)
    op.create_index(op.f('ix_generated_quests_static_id'), 'generated_quests', ['static_id'], unique=False)
    op.create_index(op.f('ix_generated_quests_id'), 'generated_quests', ['id'], unique=False)

    # ### ItemProperty ###
    op.create_table('item_properties',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('property_name_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_item_properties'))
    )
    op.create_index(op.f('ix_item_properties_guild_id'), 'item_properties', ['guild_id'], unique=False)
    op.create_index(op.f('ix_item_properties_id'), 'item_properties', ['id'], unique=False)

    # ### Item ###
    op.create_table('items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('static_id', sa.Text(), nullable=True),
        sa.Column('name_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('description_i18n', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.Column('item_type_i18n', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.Column('properties_json', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_items')),
        sa.UniqueConstraint('guild_id', 'static_id', name='_item_guild_static_id_uc')
    )
    op.create_index(op.f('ix_items_guild_id'), 'items', ['guild_id'], unique=False)
    op.create_index(op.f('ix_items_static_id'), 'items', ['static_id'], unique=False)
    op.create_index(op.f('ix_items_id'), 'items', ['id'], unique=False)

    # ### Inventory ###
    op.create_table('inventories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventories')),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], name=op.f('fk_inventories_player_id_players')),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], name=op.f('fk_inventories_item_id_items'))
    )
    op.create_index(op.f('ix_inventories_player_id'), 'inventories', ['player_id'], unique=False)
    op.create_index(op.f('ix_inventories_item_id'), 'inventories', ['item_id'], unique=False)
    op.create_index(op.f('ix_inventories_guild_id'), 'inventories', ['guild_id'], unique=False)
    op.create_index(op.f('ix_inventories_id'), 'inventories', ['id'], unique=False)

    # ### PlayerNpcMemory ###
    op.create_table('player_npc_memories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('npc_id', sa.Integer(), nullable=False),
        sa.Column('player_or_party_id', sa.BigInteger(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('memory_details_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_player_npc_memories')),
        sa.ForeignKeyConstraint(['npc_id'], ['generated_npcs.id'], name=op.f('fk_player_npc_memories_npc_id_generated_npcs'))
    )
    op.create_index(op.f('ix_player_npc_memories_guild_id'), 'player_npc_memories', ['guild_id'], unique=False)
    op.create_index(op.f('ix_player_npc_memories_npc_id'), 'player_npc_memories', ['npc_id'], unique=False)
    op.create_index(op.f('ix_player_npc_memories_player_or_party_id'), 'player_npc_memories', ['player_or_party_id'], unique=False)
    op.create_index(op.f('ix_player_npc_memories_id'), 'player_npc_memories', ['id'], unique=False)

    # ### Ability ###
    op.create_table('abilities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('static_id', sa.Text(), nullable=True),
        sa.Column('name_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('description_i18n', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_abilities')),
        sa.UniqueConstraint('guild_id', 'static_id', name='_ability_guild_static_id_uc')
    )
    op.create_index(op.f('ix_abilities_guild_id'), 'abilities', ['guild_id'], unique=False)
    op.create_index(op.f('ix_abilities_static_id'), 'abilities', ['static_id'], unique=False)
    op.create_index(op.f('ix_abilities_id'), 'abilities', ['id'], unique=False)

    # ### StatusEffect ###
    op.create_table('status_effects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('static_id', sa.Text(), nullable=True),
        sa.Column('name_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('description_i18n', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_status_effects')),
        sa.UniqueConstraint('guild_id', 'static_id', name='_status_effect_guild_static_id_uc')
    )
    op.create_index(op.f('ix_status_effects_guild_id'), 'status_effects', ['guild_id'], unique=False)
    op.create_index(op.f('ix_status_effects_static_id'), 'status_effects', ['static_id'], unique=False)
    op.create_index(op.f('ix_status_effects_id'), 'status_effects', ['id'], unique=False)

    # ### Questline ###
    op.create_table('questlines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('static_id', sa.Text(), nullable=True),
        sa.Column('name_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('description_i18n', sa.JSON(), nullable=True, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_questlines')),
        sa.UniqueConstraint('guild_id', 'static_id', name='_questline_guild_static_id_uc')
    )
    op.create_index(op.f('ix_questlines_guild_id'), 'questlines', ['guild_id'], unique=False)
    op.create_index(op.f('ix_questlines_static_id'), 'questlines', ['static_id'], unique=False)
    op.create_index(op.f('ix_questlines_id'), 'questlines', ['id'], unique=False)

    # ### QuestStep ###
    op.create_table('quest_steps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quest_id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('step_order', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('description_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_quest_steps')),
        sa.ForeignKeyConstraint(['quest_id'], ['generated_quests.id'], name=op.f('fk_quest_steps_quest_id_generated_quests')),
        sa.UniqueConstraint('quest_id', 'step_order', name='_quest_step_order_uc')
    )
    op.create_index(op.f('ix_quest_steps_guild_id'), 'quest_steps', ['guild_id'], unique=False)
    op.create_index(op.f('ix_quest_steps_quest_id'), 'quest_steps', ['quest_id'], unique=False)
    op.create_index(op.f('ix_quest_steps_id'), 'quest_steps', ['id'], unique=False)

    # ### MobileGroup ###
    op.create_table('mobile_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('name_i18n', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('current_location_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_mobile_groups')),
        sa.ForeignKeyConstraint(['current_location_id'], ['locations.id'], name=op.f('fk_mobile_groups_current_location_id_locations'))
    )
    op.create_index(op.f('ix_mobile_groups_guild_id'), 'mobile_groups', ['guild_id'], unique=False)
    op.create_index(op.f('ix_mobile_groups_current_location_id'), 'mobile_groups', ['current_location_id'], unique=False)
    op.create_index(op.f('ix_mobile_groups_id'), 'mobile_groups', ['id'], unique=False)

    # ### CraftingRecipe ###
    op.create_table('crafting_recipes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('static_id', sa.Text(), nullable=True),
        sa.Column('result_item_id', sa.Integer(), nullable=False),
        sa.Column('ingredients_json', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_crafting_recipes')),
        sa.ForeignKeyConstraint(['result_item_id'], ['items.id'], name=op.f('fk_crafting_recipes_result_item_id_items')),
        sa.UniqueConstraint('guild_id', 'static_id', name='_crafting_recipe_guild_static_id_uc')
    )
    op.create_index(op.f('ix_crafting_recipes_guild_id'), 'crafting_recipes', ['guild_id'], unique=False)
    op.create_index(op.f('ix_crafting_recipes_static_id'), 'crafting_recipes', ['static_id'], unique=False)
    op.create_index(op.f('ix_crafting_recipes_id'), 'crafting_recipes', ['id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_crafting_recipes_id'), table_name='crafting_recipes')
    op.drop_index(op.f('ix_crafting_recipes_static_id'), table_name='crafting_recipes')
    op.drop_index(op.f('ix_crafting_recipes_guild_id'), table_name='crafting_recipes')
    op.drop_table('crafting_recipes')

    op.drop_index(op.f('ix_mobile_groups_id'), table_name='mobile_groups')
    op.drop_index(op.f('ix_mobile_groups_current_location_id'), table_name='mobile_groups')
    op.drop_index(op.f('ix_mobile_groups_guild_id'), table_name='mobile_groups')
    op.drop_table('mobile_groups')

    op.drop_index(op.f('ix_quest_steps_id'), table_name='quest_steps')
    op.drop_index(op.f('ix_quest_steps_quest_id'), table_name='quest_steps')
    op.drop_index(op.f('ix_quest_steps_guild_id'), table_name='quest_steps')
    op.drop_table('quest_steps')

    op.drop_index(op.f('ix_questlines_id'), table_name='questlines')
    op.drop_index(op.f('ix_questlines_static_id'), table_name='questlines')
    op.drop_index(op.f('ix_questlines_guild_id'), table_name='questlines')
    op.drop_table('questlines')

    op.drop_index(op.f('ix_status_effects_id'), table_name='status_effects')
    op.drop_index(op.f('ix_status_effects_static_id'), table_name='status_effects')
    op.drop_index(op.f('ix_status_effects_guild_id'), table_name='status_effects')
    op.drop_table('status_effects')

    op.drop_index(op.f('ix_abilities_id'), table_name='abilities')
    op.drop_index(op.f('ix_abilities_static_id'), table_name='abilities')
    op.drop_index(op.f('ix_abilities_guild_id'), table_name='abilities')
    op.drop_table('abilities')

    op.drop_index(op.f('ix_player_npc_memories_id'), table_name='player_npc_memories')
    op.drop_index(op.f('ix_player_npc_memories_player_or_party_id'), table_name='player_npc_memories')
    op.drop_index(op.f('ix_player_npc_memories_npc_id'), table_name='player_npc_memories')
    op.drop_index(op.f('ix_player_npc_memories_guild_id'), table_name='player_npc_memories')
    op.drop_table('player_npc_memories')

    op.drop_index(op.f('ix_inventories_id'), table_name='inventories')
    op.drop_index(op.f('ix_inventories_guild_id'), table_name='inventories')
    op.drop_index(op.f('ix_inventories_item_id'), table_name='inventories')
    op.drop_index(op.f('ix_inventories_player_id'), table_name='inventories')
    op.drop_table('inventories')

    op.drop_index(op.f('ix_items_id'), table_name='items')
    op.drop_index(op.f('ix_items_static_id'), table_name='items')
    op.drop_index(op.f('ix_items_guild_id'), table_name='items')
    op.drop_table('items')

    op.drop_index(op.f('ix_item_properties_id'), table_name='item_properties')
    op.drop_index(op.f('ix_item_properties_guild_id'), table_name='item_properties')
    op.drop_table('item_properties')

    op.drop_index(op.f('ix_generated_quests_id'), table_name='generated_quests')
    op.drop_index(op.f('ix_generated_quests_static_id'), table_name='generated_quests')
    op.drop_index(op.f('ix_generated_quests_guild_id'), table_name='generated_quests')
    op.drop_table('generated_quests')

    op.drop_index(op.f('ix_generated_factions_id'), table_name='generated_factions')
    op.drop_index(op.f('ix_generated_factions_static_id'), table_name='generated_factions')
    op.drop_index(op.f('ix_generated_factions_guild_id'), table_name='generated_factions')
    op.drop_table('generated_factions')

    op.drop_index(op.f('ix_generated_npcs_id'), table_name='generated_npcs')
    op.drop_index(op.f('ix_generated_npcs_static_id'), table_name='generated_npcs')
    op.drop_index(op.f('ix_generated_npcs_location_id'), table_name='generated_npcs')
    op.drop_index(op.f('ix_generated_npcs_guild_id'), table_name='generated_npcs')
    op.drop_table('generated_npcs')
    # ### end Alembic commands ###
