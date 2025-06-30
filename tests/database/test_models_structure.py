import pytest
from sqlalchemy import inspect, String, JSON, Integer, Boolean
from sqlalchemy.dialects.postgresql import JSONB

from bot.database.models.config_related import GuildConfig, RulesConfig, UserSettings
from bot.database.models.character_related import Player, Character, Party, NPC, GeneratedNpc, RPGCharacter, PlayerNpcMemory
from bot.database.models.world_related import Location, GeneratedLocation, WorldState, GeneratedFaction, MobileGroup, LocationTemplate
from bot.database.models.item_related import ItemTemplate, Item, Inventory, ItemProperty, NewItem, NewCharacterItem, Shop, Currency
from bot.database.models.quest_related import QuestTable, GeneratedQuest, Questline, QuestStepTable
from bot.database.models.game_mechanics import Ability, Skill, Status, CraftingRecipe, Relationship, Combat
from bot.database.models.log_event_related import StoryLog

def get_column_python_type(column):
    try:
        return column.type.python_type
    except NotImplementedError:
        if hasattr(column.type, 'impl') and hasattr(column.type.impl, 'python_type'):
            return column.type.impl.python_type
        return type(column.type)

def test_guild_config_structure():
    inspector = inspect(GuildConfig)
    columns = {col.name: col for col in inspector.columns}

    assert 'guild_id' in columns
    assert isinstance(columns['guild_id'].type, String)
    assert columns['guild_id'].primary_key is True
    assert columns['guild_id'].index is True

    assert 'bot_language' in columns
    assert isinstance(columns['bot_language'].type, String)
    assert columns['bot_language'].default.arg == 'en'

    expected_channel_fields = ['game_channel_id', 'master_channel_id', 'system_channel_id', 'notification_channel_id']
    for field_name in expected_channel_fields:
        assert field_name in columns
        assert isinstance(columns[field_name].type, String)
        assert columns[field_name].nullable is True

MODELS_TO_CHECK_GUILD_SCOPING = [
    RulesConfig, UserSettings, Player, Character, Party, NPC, GeneratedNpc, RPGCharacter, PlayerNpcMemory,
    Location, GeneratedLocation, WorldState, GeneratedFaction, MobileGroup, LocationTemplate,
    ItemTemplate, Item, Inventory, ItemProperty, NewItem, NewCharacterItem, Shop, Currency,
    QuestTable, GeneratedQuest, Questline, QuestStepTable,
    Ability, Skill, Status, StoryLog
]
I18N_FIELDS_TO_CHECK = {
    RulesConfig: [],
    Player: ['name_i18n'],
    Character: ['name_i18n', 'character_class_i18n', 'race_i18n', 'description_i18n'],
    Party: ['name_i18n'],
    NPC: ['name_i18n', 'description_i18n', 'backstory_i18n', 'persona_i18n'],
    GeneratedNpc: ['name_i18n', 'description_i18n', 'backstory_i18n', 'persona_i18n'],
    Location: ['name_i18n', 'descriptions_i18n', 'type_i18n', 'details_i18n', 'tags_i18n', 'atmosphere_i18n', 'features_i18n'],
    GeneratedLocation: ['name_i18n', 'descriptions_i18n', 'details_i18n', 'tags_i18n', 'atmosphere_i18n', 'features_i18n'],
    WorldState: ['global_narrative_state_i18n', 'current_era_i18n'],
    GeneratedFaction: ['name_i18n', 'ideology_i18n', 'description_i18n', 'leader_concept_i18n', 'resource_notes_i18n'],
    MobileGroup: ['name_i18n', 'description_i18n'],
    ItemTemplate: ['name_i18n', 'description_i18n'],
    Item: ['name_i18n', 'description_i18n'],
    ItemProperty: ['name_i18n', 'description_i18n'],
    Shop: ['name_i18n', 'description_i18n', 'type_i18n'],
    Currency: ['name_i18n', 'symbol_i18n'],
    QuestTable: ['name_i18n', 'description_i18n', 'quest_giver_details_i18n', 'consequences_summary_i18n'],
    GeneratedQuest: ['title_i18n', 'description_i18n', 'quest_giver_details_i18n', 'consequences_summary_i18n'],
    Questline: ['name_i18n'],
    QuestStepTable: ['title_i18n', 'description_i18n', 'requirements_i18n'],
    Ability: ['name_i18n', 'description_i18n'],
    Skill: ['name_i18n', 'description_i18n'],
    Status: ['name_i18n', 'description_i18n'],
    StoryLog: [],
}

@pytest.mark.parametrize("model_class", MODELS_TO_CHECK_GUILD_SCOPING)
def test_model_has_guild_id_column(model_class):
    inspector = inspect(model_class)
    columns = {col.name: col for col in inspector.columns}

    assert 'guild_id' in columns, f"'guild_id' column missing in {model_class.__name__}"

    guild_id_col = columns['guild_id']
    assert isinstance(guild_id_col.type, String), \
        f"'guild_id' in {model_class.__name__} is not String type (found {guild_id_col.type})"

    fk_found = False
    for fk in guild_id_col.foreign_keys:
        if fk.column.table.name == GuildConfig.__tablename__ and fk.column.name == 'guild_id':
            fk_found = True
            break
    assert fk_found, f"'guild_id' in {model_class.__name__} does not have FK to guild_configs.guild_id"

    assert guild_id_col.index is True or \
           any(guild_id_col.name in idx.columns.keys() for idx in inspector.indexes), \
           f"'guild_id' in {model_class.__name__} is not indexed or part of a composite index"


@pytest.mark.parametrize("model_class, i18n_field_names", [
    (m, fields) for m, fields in I18N_FIELDS_TO_CHECK.items() if fields
])
def test_model_i18n_fields_are_json_variant(model_class, i18n_field_names):
    inspector = inspect(model_class)
    columns = {col.name: col for col in inspector.columns}

    for field_name in i18n_field_names:
        assert field_name in columns, f"Field '{field_name}' missing in {model_class.__name__}"
        from bot.database.base import JsonVariant as CustomJsonVariantType
        assert isinstance(columns[field_name].type, CustomJsonVariantType), \
            f"Field '{field_name}' in {model_class.__name__} is not JsonVariant (found {columns[field_name].type})"

def test_rules_config_unique_constraint():
    inspector = inspect(RulesConfig)
    unique_constraints = [uc.name for uc in inspector.selectable.constraints if isinstance(uc, pytest.importorskip('sqlalchemy.sql.schema').UniqueConstraint)]
    assert 'uq_guild_rule_key' in unique_constraints

def test_player_unique_constraint():
    inspector = inspect(Player)
    unique_constraints = [uc.name for uc in inspector.selectable.constraints if isinstance(uc, pytest.importorskip('sqlalchemy.sql.schema').UniqueConstraint)]
    assert 'uq_player_discord_guild' in unique_constraints

def test_location_model_structure():
    inspector = inspect(Location)
    columns = {col.name: col for col in inspector.columns}

    expected_fields = {
        'id': String,
        'guild_id': String,
        'static_id': String,
        'name_i18n': JSON,
        'descriptions_i18n': JSON,
        'type_i18n': JSON,
        'coordinates': JSON,
        'neighbor_locations_json': JSON,
        'generated_details_json': JSON,
        'ai_metadata_json': JSON,
        'inventory': JSON,
        'npc_ids': JSON,
        'event_triggers': JSON,
        'template_id': String,
        'state_variables': JSON,
        'is_active': Boolean,
        'details_i18n': JSON,
        'tags_i18n': JSON,
        'atmosphere_i18n': JSON,
        'features_i18n': JSON,
        'channel_id': String,
        'image_url': String,
        'points_of_interest_json': JSON,
        'on_enter_events_json': JSON,
    }

    from bot.database.base import JsonVariant as CustomJsonVariantType

    for field_name, expected_type_class in expected_fields.items():
        assert field_name in columns, f"Field '{field_name}' missing in Location model"
        col_type = columns[field_name].type
        if expected_type_class == JSON:
            assert isinstance(col_type, CustomJsonVariantType), \
                f"Field '{field_name}' in Location is not JsonVariant (found {col_type})"
        elif expected_type_class is not None:
             assert isinstance(col_type, expected_type_class), \
                f"Field '{field_name}' in Location is not {expected_type_class.__name__} (found {col_type})"

    assert columns['id'].primary_key is True
    assert columns['static_id'].index is True
    assert columns['guild_id'].index is True

    unique_constraints = [uc.name for uc in inspector.selectable.constraints if isinstance(uc, pytest.importorskip('sqlalchemy.sql.schema').UniqueConstraint)]
    assert 'uq_location_guild_static_id' in unique_constraints

MODELS_TO_CHECK_GUILD_SCOPING_UPDATED = [
    RulesConfig, UserSettings, Player, Character, Party, NPC, GeneratedNpc, RPGCharacter, PlayerNpcMemory,
    Location, GeneratedLocation, WorldState, GeneratedFaction, MobileGroup, LocationTemplate,
    ItemTemplate, Item, Inventory, ItemProperty, NewItem, NewCharacterItem, Shop, Currency,
    QuestTable, GeneratedQuest, Questline, QuestStepTable,
    Ability, Skill, Status, CraftingRecipe, Relationship, StoryLog,
    Combat
]

I18N_FIELDS_TO_CHECK_UPDATED = {
    RulesConfig: [],
    Player: ['name_i18n'],
    Character: ['name_i18n', 'character_class_i18n', 'race_i18n', 'description_i18n'],
    Party: ['name_i18n'],
    NPC: ['name_i18n', 'description_i18n', 'backstory_i18n', 'persona_i18n'],
    GeneratedNpc: ['name_i18n', 'description_i18n', 'backstory_i18n', 'persona_i18n'],
    Location: ['name_i18n', 'descriptions_i18n', 'type_i18n', 'details_i18n', 'tags_i18n', 'atmosphere_i18n', 'features_i18n'],
    GeneratedLocation: ['name_i18n', 'descriptions_i18n', 'details_i18n', 'tags_i18n', 'atmosphere_i18n', 'features_i18n'],
    WorldState: ['global_narrative_state_i18n', 'current_era_i18n'],
    GeneratedFaction: ['name_i18n', 'ideology_i18n', 'description_i18n', 'leader_concept_i18n', 'resource_notes_i18n'],
    MobileGroup: ['name_i18n', 'description_i18n'],
    ItemTemplate: ['name_i18n', 'description_i18n'],
    Item: ['name_i18n', 'description_i18n'],
    ItemProperty: ['name_i18n', 'description_i18n'],
    Shop: ['name_i18n', 'description_i18n', 'type_i18n'],
    Currency: ['name_i18n', 'symbol_i18n'],
    QuestTable: ['name_i18n', 'description_i18n', 'quest_giver_details_i18n', 'consequences_summary_i18n'],
    GeneratedQuest: ['title_i18n', 'description_i18n', 'quest_giver_details_i18n', 'consequences_summary_i18n'],
    Questline: ['name_i18n'],
    QuestStepTable: ['title_i18n', 'description_i18n', 'requirements_i18n'],
    Ability: ['name_i18n', 'description_i18n', 'effect_i18n', 'type_i18n'],
    Skill: ['name_i18n', 'description_i18n'],
    Status: ['name_i18n', 'description_i18n'],
    CraftingRecipe: ['name_i18n', 'description_i18n'],
    StoryLog: [],
    Combat: [],
    Relationship: [],
    PlayerNpcMemory: ['memory_details_i18n'],
}

@pytest.mark.parametrize("model_class", MODELS_TO_CHECK_GUILD_SCOPING_UPDATED)
def test_model_has_guild_id_column_updated(model_class):
    inspector = inspect(model_class)
    columns = {col.name: col for col in inspector.columns}

    assert 'guild_id' in columns, f"'guild_id' column missing in {model_class.__name__}"

    guild_id_col = columns['guild_id']
    assert isinstance(guild_id_col.type, String), \
        f"'guild_id' in {model_class.__name__} is not String type (found {guild_id_col.type})"

    fk_found = False
    for fk in guild_id_col.foreign_keys:
        if fk.column.table.name == GuildConfig.__tablename__ and fk.column.name == 'guild_id':
            fk_found = True
            break
    assert fk_found, f"'guild_id' in {model_class.__name__} does not have FK to guild_configs.guild_id"

    assert guild_id_col.index is True or \
           any(guild_id_col.name in idx.columns.keys() for idx in inspector.indexes), \
           f"'guild_id' in {model_class.__name__} is not indexed or part of a composite index"

@pytest.mark.parametrize("model_class, i18n_field_names", [
    (m, fields) for m, fields in I18N_FIELDS_TO_CHECK_UPDATED.items() if fields
])
def test_model_i18n_fields_are_json_variant_updated(model_class, i18n_field_names):
    inspector = inspect(model_class)
    columns = {col.name: col for col in inspector.columns}
    from bot.database.base import JsonVariant as CustomJsonVariantType

    for field_name in i18n_field_names:
        assert field_name in columns, f"Field '{field_name}' missing in {model_class.__name__}"
        assert isinstance(columns[field_name].type, CustomJsonVariantType), \
            f"Field '{field_name}' in {model_class.__name__} is not JsonVariant (found {columns[field_name].type})"

def test_combat_encounter_model_structure():
    inspector = inspect(Combat)
    columns = {col.name: col for col in inspector.columns}
    from bot.database.base import JsonVariant as CustomJsonVariantType
    from sqlalchemy import Text

    assert 'location_id' in columns
    assert isinstance(columns['location_id'].type, String)
    assert any(fk.column.table.name == 'locations' for fk in columns['location_id'].foreign_keys)

    assert 'status' in columns
    assert isinstance(columns['status'].type, String)
    assert columns['status'].type.length == 50

    assert 'current_turn_index' in columns
    assert isinstance(columns['current_turn_index'].type, Integer)
    assert 'turn_order' in columns
    assert isinstance(columns['turn_order'].type, CustomJsonVariantType)

    assert 'participants' in columns
    assert isinstance(columns['participants'].type, CustomJsonVariantType)

    assert 'combat_rules_snapshot' in columns
    assert isinstance(columns['combat_rules_snapshot'].type, CustomJsonVariantType)

    assert 'combat_log' in columns
    assert isinstance(columns['combat_log'].type, Text)
    assert 'turn_log_structured' in columns
    assert isinstance(columns['turn_log_structured'].type, CustomJsonVariantType)
