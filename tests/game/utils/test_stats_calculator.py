# tests/game/utils/test_stats_calculator.py
import pytest
import json
from unittest.mock import MagicMock, AsyncMock

from bot.game.utils.stats_calculator import calculate_effective_stats
from bot.database.models import Player, Character as DBCharacter, NPC as DBNPC, Item as DBItem, Status as DBStatus
# Assuming Pydantic models are not directly used by calculate_effective_stats, but DB models are.
# If Pydantic models are indeed passed, those should be mocked/used.
# Based on calculate_effective_stats signature, it takes Union[Player, NPC, Character] which are DB models.

from bot.game.managers.game_manager import GameManager
from bot.game.managers.equipment_manager import EquipmentManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.rule_engine import RuleEngine # For get_rule

# --- Mock Data & Fixtures ---

@pytest.fixture
def mock_game_manager():
    gm = MagicMock(spec=GameManager)
    gm.db_service = AsyncMock(name="DBService") # Not directly used by calc, but often part of GM

    gm.equipment_manager = AsyncMock(spec=EquipmentManager)
    gm.equipment_manager.get_equipped_item_instances = AsyncMock(return_value=[]) # Default no items

    gm.status_manager = AsyncMock(spec=StatusManager)
    gm.status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[]) # Default no statuses

    gm.rule_engine = AsyncMock(spec=RuleEngine)
    # Default get_rule behavior
    async def default_get_rule(guild_id, rule_key, default=None):
        rules = {
            "rules.combat.base_hp": 10,
            "rules.combat.hp_per_con_point": 2,
            "rules.combat.base_ac": 10,
            "rules.character.proficiency_bonus_per_level": 0.25,
            "rules.character.base_proficiency_bonus": 2,
            "rules.magic.spell_dc_base": 8
        }
        return rules.get(rule_key, default)
    gm.get_rule = AsyncMock(side_effect=default_get_rule)

    # Mock other managers if they become relevant for stat calculation (e.g., passive abilities from AbilityManager)
    return gm

@pytest.fixture
def db_character_entity():
    char = MagicMock(spec=DBCharacter)
    char.id = "char1"
    char.guild_id = "guild1"
    char.stats_json = json.dumps({
        "strength": 12, "dexterity": 14, "constitution": 13,
        "intelligence": 10, "wisdom": 8, "charisma": 15,
        "level": 5 # Add level for proficiency bonus calculation
    })
    # Ensure other attributes that might be accessed exist, even if None
    char.name_i18n = {"en": "Test Char"} # For logging
    return char

@pytest.fixture
def db_npc_entity():
    npc = MagicMock(spec=DBNPC)
    npc.id = "npc1"
    npc.guild_id = "guild1"
    # DBNPC uses 'stats' directly as a dict, not stats_json
    npc.stats = {
        "strength": 10, "dexterity": 10, "constitution": 10,
        "intelligence": 10, "wisdom": 10, "charisma": 10,
        "level": 3
    }
    npc.name_i18n = {"en": "Test NPC"} # For logging
    return npc

# --- Test Cases ---

@pytest.mark.asyncio
async def test_calculate_base_stats_character(db_character_entity: DBCharacter, mock_game_manager: GameManager):
    effective_stats = await calculate_effective_stats(db_character_entity, "guild1", mock_game_manager)

    assert effective_stats["strength"] == 12
    assert effective_stats["dexterity"] == 14
    assert effective_stats["constitution"] == 13
    assert effective_stats["intelligence"] == 10
    assert effective_stats["wisdom"] == 8
    assert effective_stats["charisma"] == 15
    assert effective_stats["level"] == 5

    # Check derived stats (based on mocked rules)
    # Proficiency = 2 + (5-1)*0.25 = 2 + 1 = 3
    # CON mod = (13-10)//2 = 1
    # DEX mod = (14-10)//2 = 2
    # STR mod = (12-10)//2 = 1
    # INT mod = (10-10)//2 = 0
    assert effective_stats["proficiency_bonus"] == 3
    assert effective_stats["max_hp"] == 10 + (13 * 2) # base_hp + (con_val * hp_per_con)
    assert effective_stats["armor_class"] == 10 + 2 # base_ac + dex_mod
    assert effective_stats["attack_bonus_melee"] == 1 + 3 # str_mod + prof
    assert effective_stats["attack_bonus_ranged"] == 2 + 3 # dex_mod + prof
    assert effective_stats["damage_bonus_melee"] == 1 # str_mod
    assert effective_stats["damage_bonus_ranged"] == 2 # dex_mod
    assert effective_stats["spell_save_dc"] == 8 + 3 + 0 # spell_dc_base + prof + int_mod
    assert effective_stats["spell_attack_bonus"] == 3 + 0 # prof + int_mod

@pytest.mark.asyncio
async def test_calculate_base_stats_npc(db_npc_entity: DBNPC, mock_game_manager: GameManager):
    effective_stats = await calculate_effective_stats(db_npc_entity, "guild1", mock_game_manager)
    assert effective_stats["strength"] == 10
    assert effective_stats["level"] == 3
    # Proficiency = 2 + (3-1)*0.25 = 2 + 0.5 = 2 (due to int conversion)
    assert effective_stats["proficiency_bonus"] == 2


@pytest.mark.asyncio
async def test_stats_with_equipment_modifiers(db_character_entity: DBCharacter, mock_game_manager: GameManager):
    # Mock equipped items
    item1 = MagicMock(spec=DBItem)
    item1.id = "item_str_sword"
    item1.properties = {"modifies_stat_strength": 2, "grants_bonus_attack_bonus_melee": 1} # Example properties

    item2 = MagicMock(spec=DBItem)
    item2.id = "item_dex_shield"
    item2.properties = {"modifies_stat_dexterity": -1, "grants_bonus_armor_class": 2} # AC is just armor_class

    mock_game_manager.equipment_manager.get_equipped_item_instances = AsyncMock(return_value=[item1, item2])

    effective_stats = await calculate_effective_stats(db_character_entity, "guild1", mock_game_manager)

    assert effective_stats["strength"] == 12 + 2 # Base 12 + 2 from sword
    assert effective_stats["dexterity"] == 14 - 1 # Base 14 - 1 from shield

    # Recalculate derived stats based on new effective STR/DEX
    # STR mod = (14-10)//2 = 2
    # DEX mod = (13-10)//2 = 1
    # Proficiency = 3 (level 5)
    assert effective_stats["armor_class"] == 10 + 1 + 2 # base + new_dex_mod + shield_ac_bonus
    assert effective_stats["attack_bonus_melee"] == 2 + 3 + 1 # new_str_mod + prof + sword_attack_bonus

@pytest.mark.asyncio
async def test_stats_with_status_effect_modifiers(db_character_entity: DBCharacter, mock_game_manager: GameManager):
    status1 = MagicMock(spec=DBStatus)
    status1.name = "Weakened"
    status1.effects = {"stat_change": {"strength": -2, "wisdom": 1}}

    status2 = MagicMock(spec=DBStatus)
    status2.name = "Agile"
    status2.effects = {"ac_bonus": 1} # This should map to bonuses['armor_class_bonus']

    mock_game_manager.status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[status1, status2])

    effective_stats = await calculate_effective_stats(db_character_entity, "guild1", mock_game_manager)

    assert effective_stats["strength"] == 12 - 2 # Base 12 - 2 from status
    assert effective_stats["wisdom"] == 8 + 1   # Base 8 + 1 from status

    # DEX mod = (14-10)//2 = 2
    # AC = 10 (base) + 2 (dex_mod) + 1 (status_ac_bonus)
    assert effective_stats["armor_class"] == 10 + 2 + 1


@pytest.mark.asyncio
async def test_stats_with_equipment_and_status_effects(db_character_entity: DBCharacter, mock_game_manager: GameManager):
    item_shield = MagicMock(spec=DBItem)
    item_shield.id = "item_magic_shield"
    item_shield.properties = {"grants_bonus_armor_class": 1} # AC is armor_class

    status_blessed = MagicMock(spec=DBStatus)
    status_blessed.name = "Blessed"
    status_blessed.effects = {"stat_change": {"strength": 2}, "attack_melee_bonus": 1} # attack_melee_bonus -> bonuses['attack_bonus_melee']

    mock_game_manager.equipment_manager.get_equipped_item_instances = AsyncMock(return_value=[item_shield])
    mock_game_manager.status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[status_blessed])

    effective_stats = await calculate_effective_stats(db_character_entity, "guild1", mock_game_manager)

    assert effective_stats["strength"] == 12 + 2 # Base 12 + 2 from status

    # STR mod = (14-10)//2 = 2
    # DEX mod = (14-10)//2 = 2
    # Proficiency = 3 (level 5)
    assert effective_stats["armor_class"] == 10 + 2 + 1 # base + dex_mod + shield_ac_bonus
    assert effective_stats["attack_bonus_melee"] == 2 + 3 + 1 # new_str_mod + prof + status_attack_bonus

@pytest.mark.asyncio
async def test_malformed_stats_json_character(db_character_entity: DBCharacter, mock_game_manager: GameManager):
    db_character_entity.stats_json = "this is not json"
    effective_stats = await calculate_effective_stats(db_character_entity, "guild1", mock_game_manager)
    # Should default to base 10 for core attributes if stats_json is invalid
    assert effective_stats["strength"] == 10
    assert effective_stats["dexterity"] == 10
    # And level should default to 1 if not found in (now empty) stats
    assert effective_stats["level"] == 1
    # Proficiency = 2 + (1-1)*0.25 = 2
    assert effective_stats["proficiency_bonus"] == 2


@pytest.mark.asyncio
async def test_character_with_no_stats_json(db_character_entity: DBCharacter, mock_game_manager: GameManager):
    db_character_entity.stats_json = None
    effective_stats = await calculate_effective_stats(db_character_entity, "guild1", mock_game_manager)
    assert effective_stats["strength"] == 10 # Defaults
    assert effective_stats["level"] == 1 # Defaults
    assert effective_stats["proficiency_bonus"] == 2

@pytest.mark.asyncio
async def test_npc_with_no_stats_attribute(db_npc_entity: DBNPC, mock_game_manager: GameManager):
    del db_npc_entity.stats # Remove the stats attribute
    effective_stats = await calculate_effective_stats(db_npc_entity, "guild1", mock_game_manager)
    assert effective_stats.get("strength", 10) == 10 # Defaults if stats missing
    assert effective_stats.get("level", 1) == 1
    assert effective_stats.get("proficiency_bonus", 2) == 2
    # Restore for other tests if fixture is session scoped, but it's function scoped here.
    # db_npc_entity.stats = {"strength": 10, "level": 3}

@pytest.mark.asyncio
async def test_player_entity_passed_directly(mock_game_manager: GameManager):
    # This tests the warning/fallback path if a Player DB model is passed
    player_db_model = MagicMock(spec=Player)
    player_db_model.id = "player_db_direct"
    player_db_model.guild_id = "guild1"
    player_db_model.name_i18n = {"en": "Player DB Direct"}
    # Player model does not have stats_json or level directly

    with pytest.logs('bot.game.utils.stats_calculator', level='WARNING') as log_capture:
        effective_stats = await calculate_effective_stats(player_db_model, "guild1", mock_game_manager)

    assert any("Received a Player entity" in record.getMessage() for record in log_capture.records)
    assert effective_stats["strength"] == 10 # Defaults
    assert effective_stats["level"] == 1 # Defaults
    assert effective_stats["proficiency_bonus"] == 2

@pytest.mark.asyncio
async def test_unknown_entity_type(mock_game_manager: GameManager):
    unknown_entity = MagicMock() # Not Player, Character, or NPC
    unknown_entity.id = "unknown_ent"

    with pytest.logs('bot.game.utils.stats_calculator', level='WARNING') as log_capture:
        effective_stats = await calculate_effective_stats(unknown_entity, "guild1", mock_game_manager)

    assert any("Unknown entity type" in record.getMessage() for record in log_capture.records)
    assert effective_stats == {} # Returns empty dict for unknown type
