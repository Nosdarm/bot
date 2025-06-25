import pytest
from sqlalchemy import inspect, String, JSON, Integer # Removed BigInteger as IDs are String
from sqlalchemy.dialects.postgresql import JSONB # For direct type check if possible, though JsonVariant handles it

from bot.database.models.config_related import GuildConfig, RulesConfig, UserSettings
from bot.database.models.character_related import Player, Character, Party, NPC, GeneratedNpc, RPGCharacter, PlayerNpcMemory
from bot.database.models.world_related import Location, GeneratedLocation, WorldState, GeneratedFaction, MobileGroup, LocationTemplate
from bot.database.models.item_related import ItemTemplate, Item, Inventory, ItemProperty, NewItem, NewCharacterItem, Shop, Currency
from bot.database.models.quest_related import QuestTable, GeneratedQuest, Questline, QuestStepTable
from bot.database.models.game_mechanics import Ability, Skill, Status # Assuming these exist
from bot.database.models.log_event_related import GameLog # Assuming this is the Log model from ТЗ

# Helper to get column type, trying to resolve to underlying Python type for JsonVariant
def get_column_python_type(column):
    try:
        return column.type.python_type
    except NotImplementedError: # Happens for custom types like JsonVariant if not directly supported
        if hasattr(column.type, 'impl') and hasattr(column.type.impl, 'python_type'): # For JsonVariant
            return column.type.impl.python_type
        return type(column.type) # Fallback to the SQLAlchemy type object itself

# --- Test for GuildConfig structure ---
def test_guild_config_structure():
    inspector = inspect(GuildConfig)
    columns = {col.name: col for col in inspector.columns}

    assert 'guild_id' in columns
    assert isinstance(columns['guild_id'].type, String) # IDs are strings
    assert columns['guild_id'].primary_key is True
    assert columns['guild_id'].index is True

    assert 'bot_language' in columns
    assert isinstance(columns['bot_language'].type, String)
    assert columns['bot_language'].default.arg == 'en'

    expected_channel_fields = ['game_channel_id', 'master_channel_id', 'system_channel_id', 'notification_channel_id']
    for field_name in expected_channel_fields:
        assert field_name in columns
        assert isinstance(columns[field_name].type, String) # Channel IDs are strings
        assert columns[field_name].nullable is True


# --- Parametrized tests for common patterns (guild_id, _i18n fields) ---

# List of models to check for guild_id and _i18n patterns
# Add all models listed in ТЗ 0.2 that should be guild-specific
MODELS_TO_CHECK_GUILD_SCOPING = [
    RulesConfig, UserSettings, Player, Character, Party, NPC, GeneratedNpc, RPGCharacter, PlayerNpcMemory,
    Location, GeneratedLocation, WorldState, GeneratedFaction, MobileGroup, LocationTemplate,
    ItemTemplate, Item, Inventory, ItemProperty, NewItem, NewCharacterItem, Shop, Currency,
    QuestTable, GeneratedQuest, Questline, QuestStepTable,
    Ability, Skill, Status, GameLog # Assuming GameLog is the model for "Log"
]
# Models that should have JsonVariant for _i18n fields (example names)
# This is a subset of the above, plus the field names to check
I18N_FIELDS_TO_CHECK = {
    RulesConfig: [], # value is JsonVariant but not typically _i18n named
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
    Item: ['name_i18n', 'description_i18n'], # If they can override template
    ItemProperty: ['name_i18n', 'description_i18n'],
    Shop: ['name_i18n', 'description_i18n', 'type_i18n'],
    Currency: ['name_i18n', 'symbol_i18n'],
    QuestTable: ['name_i18n', 'description_i18n', 'quest_giver_details_i18n', 'consequences_summary_i18n'],
    GeneratedQuest: ['title_i18n', 'description_i18n', 'quest_giver_details_i18n', 'consequences_summary_i18n'],
    Questline: ['name_i18n'],
    QuestStepTable: ['title_i18n', 'description_i18n', 'requirements_i18n'],
    Ability: ['name_i18n', 'description_i18n'], # Assuming from ТЗ
    Skill: ['name_i18n', 'description_i18n'],   # Assuming from ТЗ
    Status: ['name_i18n', 'description_i18n'],  # Assuming from ТЗ
    GameLog: [], # details_json is JsonVariant, but not _i18n named
}

@pytest.mark.parametrize("model_class", MODELS_TO_CHECK_GUILD_SCOPING)
def test_model_has_guild_id_column(model_class):
    """Checks if the model has a 'guild_id' column with expected properties."""
    inspector = inspect(model_class)
    columns = {col.name: col for col in inspector.columns}

    assert 'guild_id' in columns, f"'guild_id' column missing in {model_class.__name__}"

    guild_id_col = columns['guild_id']
    # Check type (String, as GuildConfig.guild_id is String)
    assert isinstance(guild_id_col.type, String), \
        f"'guild_id' in {model_class.__name__} is not String type (found {guild_id_col.type})"

    # Check if it's a foreign key to GuildConfig.guild_id
    fk_found = False
    for fk in guild_id_col.foreign_keys:
        if fk.column.table.name == GuildConfig.__tablename__ and fk.column.name == 'guild_id':
            fk_found = True
            break
    assert fk_found, f"'guild_id' in {model_class.__name__} does not have FK to guild_configs.guild_id"

    # Check for an index that includes guild_id (could be individual or composite)
    # This is a simple check; a more robust one would look at specific index definitions.
    assert guild_id_col.index is True or \
           any(guild_id_col.name in idx.columns.keys() for idx in inspector.indexes), \
           f"'guild_id' in {model_class.__name__} is not indexed or part of a composite index"


@pytest.mark.parametrize("model_class, i18n_field_names", [
    (m, fields) for m, fields in I18N_FIELDS_TO_CHECK.items() if fields # Only test models that have i18n fields listed
])
def test_model_i18n_fields_are_json_variant(model_class, i18n_field_names):
    """Checks if specified _i18n fields in a model are of JsonVariant type (implying JSON/JSONB)."""
    inspector = inspect(model_class)
    columns = {col.name: col for col in inspector.columns}

    for field_name in i18n_field_names:
        assert field_name in columns, f"Field '{field_name}' missing in {model_class.__name__}"
        # Check underlying Python type for JsonVariant
        # This relies on JsonVariant having a python_type attribute or similar introspection.
        # A simpler check might be `isinstance(columns[field_name].type, JsonVariant)`.
        # For now, let's assume JsonVariant is the direct type.
        from bot.database.base import JsonVariant as CustomJsonVariantType
        assert isinstance(columns[field_name].type, CustomJsonVariantType), \
            f"Field '{field_name}' in {model_class.__name__} is not JsonVariant (found {columns[field_name].type})"


# Example test for a specific model's unique constraints (if applicable)
def test_rules_config_unique_constraint():
    inspector = inspect(RulesConfig)
    unique_constraints = [uc.name for uc in inspector.constraints if isinstance(uc, pytest.importorskip('sqlalchemy.sql.schema').UniqueConstraint)]
    assert 'uq_guild_rule_key' in unique_constraints

def test_player_unique_constraint():
    inspector = inspect(Player)
    unique_constraints = [uc.name for uc in inspector.constraints if isinstance(uc, pytest.importorskip('sqlalchemy.sql.schema').UniqueConstraint)]
    assert 'uq_player_discord_guild' in unique_constraints

# --- Test for Location structure (Task 1.1) ---
def test_location_model_structure():
    inspector = inspect(Location)
    columns = {col.name: col for col in inspector.columns}

    # Fields from ТЗ 1.1 and their expected types (simplified)
    # Note: Model uses JsonVariant for most complex types, which is consistent with JSONB.
    # Model also uses direct Column definitions, not Mapped.
    expected_fields = {
        'id': String, # PK
        'guild_id': String, # FK, Checked by test_model_has_guild_id_column
        'static_id': String,
        'name_i18n': JSON, # Underlying type for JsonVariant
        'descriptions_i18n': JSON,
        'type_i18n': JSON, # Model has type_i18n, ТЗ has type (TEXT enum) - JsonVariant is flexible
        'coordinates': JSON, # Model has 'coordinates', ТЗ has 'coordinates_json' - name diff, type ok
        'neighbor_locations_json': JSON,
        'generated_details_json': JSON,
        'ai_metadata_json': JSON,
        # Other fields present in the model definition from world_related.py
        'inventory': JSON,
        'npc_ids': JSON,
        'event_triggers': JSON,
        'template_id': String,
        'state_variables': JSON,
        'is_active': Boolean if hasattr(columns.get('is_active'), 'type') and isinstance(columns.get('is_active').type, pytest.importorskip('sqlalchemy.sql.sqltypes').Boolean) else None, # type: ignore
        'details_i18n': JSON,
        'tags_i18n': JSON,
        'atmosphere_i18n': JSON,
        'features_i18n': JSON,
        'channel_id': String,
        'image_url': String,
        'points_of_interest_json': JSON,
        'on_enter_events_json': JSON,
    }

    # Check for type.python_type for JsonVariant if possible
    from bot.database.base import JsonVariant as CustomJsonVariantType

    for field_name, expected_type_class in expected_fields.items():
        assert field_name in columns, f"Field '{field_name}' missing in Location model"
        col_type = columns[field_name].type
        if expected_type_class == JSON: # For JsonVariant fields
            assert isinstance(col_type, CustomJsonVariantType), \
                f"Field '{field_name}' in Location is not JsonVariant (found {col_type})"
        elif expected_type_class is not None: # For String, Boolean etc.
             assert isinstance(col_type, expected_type_class), \
                f"Field '{field_name}' in Location is not {expected_type_class.__name__} (found {col_type})"

    # Check specific properties
    assert columns['id'].primary_key is True
    assert columns['static_id'].index is True
    assert columns['guild_id'].index is True # Redundant if covered by general guild_id check, but good for clarity

    # Check UniqueConstraint for (guild_id, static_id)
    unique_constraints = [uc.name for uc in inspector.constraints if isinstance(uc, pytest.importorskip('sqlalchemy.sql.schema').UniqueConstraint)]
    assert 'uq_location_guild_static_id' in unique_constraints


# TODO: Add more specific checks for other models if they have complex constraints or relationships
#       that are critical to the "Guild ID scoping" aspect beyond just the FK.

# This file provides basic structural checks.
# Integration tests (like test_guild_initializer.py) will confirm
# that these models work correctly with the database (e.g., tables created, FKs enforced by DB).


# --- Updated lists for Task 2.1 ---
MODELS_TO_CHECK_GUILD_SCOPING_UPDATED = [
    RulesConfig, UserSettings, Player, Character, Party, NPC, GeneratedNpc, RPGCharacter, PlayerNpcMemory,
    Location, GeneratedLocation, WorldState, GeneratedFaction, MobileGroup, LocationTemplate,
    ItemTemplate, Item, Inventory, ItemProperty, NewItem, NewCharacterItem, Shop, Currency,
    QuestTable, GeneratedQuest, Questline, QuestStepTable,
    Ability, Skill, Status, CraftingRecipe, Relationship, StoryLog, # Added from game_mechanics & log_event_related
    Combat # Added from game_mechanics
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

# --- Re-parameterize tests with updated lists ---

@pytest.mark.parametrize("model_class", MODELS_TO_CHECK_GUILD_SCOPING_UPDATED)
def test_model_has_guild_id_column_updated(model_class):
    """Checks if the model has a 'guild_id' column with expected properties (using updated list)."""
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
    """Checks if specified _i18n fields in a model are JsonVariant (using updated list)."""
    inspector = inspect(model_class)
    columns = {col.name: col for col in inspector.columns}
    from bot.database.base import JsonVariant as CustomJsonVariantType

    for field_name in i18n_field_names:
        assert field_name in columns, f"Field '{field_name}' missing in {model_class.__name__}"
        assert isinstance(columns[field_name].type, CustomJsonVariantType), \
            f"Field '{field_name}' in {model_class.__name__} is not JsonVariant (found {columns[field_name].type})"


# --- Test for Combat (CombatEncounter) structure (Task 22) ---
def test_combat_encounter_model_structure():
    inspector = inspect(Combat) # Make sure Combat is imported from game_mechanics
    columns = {col.name: col for col in inspector.columns}
    from bot.database.base import JsonVariant as CustomJsonVariantType
    from sqlalchemy import Text # For combat_log

    # Fields from ТЗ 22 (mapping to model 'Combat')
    # id: PK (String, default uuid) - Covered by default model structure
    # guild_id: FK (String) - Covered by test_model_has_guild_id_column_updated

    assert 'location_id' in columns
    assert isinstance(columns['location_id'].type, String)
    assert any(fk.column.table.name == 'locations' for fk in columns['location_id'].foreign_keys)

    assert 'status' in columns
    assert isinstance(columns['status'].type, String)
    assert columns['status'].type.length == 50

    assert 'current_turn_index' in columns # Model uses current_turn_index
    assert isinstance(columns['current_turn_index'].type, Integer)
    assert 'turn_order' in columns # ТЗ: turn_order_json
    assert isinstance(columns['turn_order'].type, CustomJsonVariantType)

    assert 'participants' in columns # ТЗ: participants_json
    assert isinstance(columns['participants'].type, CustomJsonVariantType)

    assert 'combat_rules_snapshot' in columns # ТЗ: rules_config_snapshot_json
    assert isinstance(columns['combat_rules_snapshot'].type, CustomJsonVariantType)

    assert 'combat_log' in columns # ТЗ: combat_log_json (JSONB), Model: Text
    assert isinstance(columns['combat_log'].type, Text)
    assert 'turn_log_structured' in columns # This is likely the JSONB equivalent for combat log
    assert isinstance(columns['turn_log_structured'].type, CustomJsonVariantType)
# Removed the print statement below as it's not part of the test code itself
