import logging
from typing import Dict, Union, TYPE_CHECKING, Any, List # Add List
import copy # For deepcopy

import json # Ensure json is imported
# Assuming Player and NPC models are correctly imported where this function is called
# or passed as type hints effectively.
from bot.database.models import Player, NPC, Item, Status, Character # Added Character, Item, Status, NPC
# For NPC, if it's defined in bot.game.models.npc (not bot.database.models.NPC)
# from bot.game.models.npc import NPC # Adjust if NPC model path is different

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager
    # from bot.database.models import NPC # Already imported above

logger = logging.getLogger(__name__)

async def calculate_effective_stats(
    entity: Union[Player, NPC, Character],
    guild_id: str,
    game_manager: 'GameManager'
) -> Dict[str, Any]:
    """
    Calculates the effective stats for a given entity (Player, Character or NPC)
    by applying modifiers from equipment, status effects, etc.
    """
    base_stats_source = None
    entity_id_for_log = getattr(entity, 'id', 'Unknown Entity')
    entity_type_str = "unknown" # Default entity type for logging/processing

    if isinstance(entity, Character):
        entity_type_str = "character"
        if hasattr(entity, 'stats_json') and entity.stats_json:
            if isinstance(entity.stats_json, str):
                try:
                    base_stats_source = json.loads(entity.stats_json)
                except json.JSONDecodeError:
                    logger.warning(f"StatsCalculator: Invalid JSON in stats_json for Character {entity_id_for_log}.")
                    base_stats_source = {}
            elif isinstance(entity.stats_json, dict):
                base_stats_source = entity.stats_json # Already a dict
            else:
                logger.warning(f"StatsCalculator: stats_json for Character {entity_id_for_log} is not a string or dict, type: {type(entity.stats_json)}.")
                base_stats_source = {}
        else:
            logger.warning(f"StatsCalculator: Character {entity_id_for_log} has no stats_json attribute or it's empty.")
            base_stats_source = {}
    elif isinstance(entity, NPC):
        entity_type_str = "npc"
        # NPCs from DB model have 'stats' as a dict, or 'stats_json' if that's how templates are stored before instantiation
        if hasattr(entity, 'stats') and isinstance(entity.stats, dict):
            base_stats_source = entity.stats
        elif hasattr(entity, 'stats_json') and entity.stats_json: # Fallback for NPC if it uses stats_json
            if isinstance(entity.stats_json, str):
                try:
                    base_stats_source = json.loads(entity.stats_json)
                except json.JSONDecodeError:
                    logger.warning(f"StatsCalculator: Invalid JSON in stats_json for NPC {entity_id_for_log}.")
                    base_stats_source = {}
            elif isinstance(entity.stats_json, dict):
                 base_stats_source = entity.stats_json
            else:
                logger.warning(f"StatsCalculator: stats_json for NPC {entity_id_for_log} is not a string or dict, type: {type(entity.stats_json)}.")
                base_stats_source = {}
        else:
            logger.warning(f"StatsCalculator: NPC {entity_id_for_log} has neither 'stats' (dict) nor 'stats_json' attribute.")
            base_stats_source = {}
    elif isinstance(entity, Player):
        entity_type_str = "player" # For logging/equipment fetching context
        logger.warning(f"StatsCalculator: Received a Player entity ({entity_id_for_log}) directly. Effective stats should be calculated for its active Character. This function might not yield complete results for Player type directly if it expects character-specific stats sources like stats_json.")
        # Player model itself doesn't have stats_json. If this path is taken, base_stats_source will remain None.
        # The function will then likely return {} or stats based on defaults only.
        # This case should ideally be handled by the caller by passing the Character object.
        base_stats_source = {} # Player has no direct stats, stats come from Character
    else:
        logger.warning(f"StatsCalculator: Unknown entity type for {entity_id_for_log}. Type: {type(entity)}. Cannot determine base stats source.")
        return {}

    if not base_stats_source: # Catches if base_stats_source remained None or was set to {}
        logger.warning(f"StatsCalculator: No base stats successfully loaded for entity {entity_id_for_log} (type: {type(entity).__name__}). Effective stats will be based on defaults or be empty.")
        # Initialize with empty dict if it's None, to allow deepcopy and default attribute setting
        base_stats_source = {}

    effective_stats = copy.deepcopy(base_stats_source)

    # Ensure base attributes are integers, default to 10 if missing or invalid
    base_attributes = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    for attr in base_attributes:
        val = effective_stats.get(attr, 10)
        try:
            effective_stats[attr] = int(val)
        except (ValueError, TypeError):
            logger.warning(f"StatsCalculator: Invalid base value for {attr} ('{val}') for entity {entity.id}. Defaulting to 10.")
            effective_stats[attr] = 10

    # Initialize accumulators for bonuses that are not direct stat modifications
    # but contribute to derived stats (like AC from multiple armor pieces)
    # These are temporary and will be summed into final derived stats.
    bonuses = {
        "armor_class_bonus": 0,
        "attack_bonus_melee": 0,
        "attack_bonus_ranged": 0,
        "damage_bonus_melee": 0,
        "damage_bonus_ranged": 0,
        # Add other specific bonus types as needed
    }

    # 1. Equipment Modifiers
    if game_manager.equipment_manager and game_manager.item_manager:
        try:
            # This method would need to be implemented in EquipmentManager
            equipped_items: List[Item] = [] # Type hint with SQLAlchemy Item
            if hasattr(game_manager.equipment_manager, 'get_equipped_item_instances'):
                 equipped_items = await game_manager.equipment_manager.get_equipped_item_instances(
                    entity_id=str(entity.id), # Ensure ID is string
                    entity_type=entity_type_str, # Pass determined entity_type
                    guild_id=guild_id
                )
            else:
                logger.debug(f"StatsCalculator: EquipmentManager missing 'get_equipped_item_instances' for entity {entity.id}")

            for item in equipped_items: # item is now expected to be an SQLAlchemy Item model instance
                if hasattr(item, 'properties') and isinstance(item.properties, dict): # Accessing properties directly
                    for prop_key, prop_value in item.properties.items():
                        if prop_key.startswith("modifies_stat_"):
                            stat_name = prop_key.replace("modifies_stat_", "")
                            effective_stats[stat_name] = effective_stats.get(stat_name, 0) + int(prop_value)
                        elif prop_key.startswith("grants_bonus_"): # e.g., grants_bonus_armor_class
                            bonus_type = prop_key.replace("grants_bonus_", "") # e.g. "armor_class"
                            # Ensure the key matches keys in 'bonuses' dict
                            full_bonus_key = f"{bonus_type}_bonus" # e.g. "armor_class_bonus" - this might need adjustment based on actual item prop keys
                            if bonus_type in bonuses : # e.g. item has "grants_bonus_armor_class" -> bonus_type = "armor_class", but bonuses stores "armor_class_bonus"
                                 key_to_use = bonus_type + "_bonus" if bonus_type + "_bonus" in bonuses else bonus_type
                                 bonuses[key_to_use] = bonuses.get(key_to_use, 0) + int(prop_value)
                            elif full_bonus_key in bonuses:
                                bonuses[full_bonus_key] = bonuses.get(full_bonus_key, 0) + int(prop_value)
                            else:
                                logger.warning(f"StatsCalculator: Unknown bonus type '{bonus_type}' or '{full_bonus_key}' from item {getattr(item, 'id', 'Unknown')} for entity {entity.id}")

        except Exception as e:
            logger.error(f"StatsCalculator: Error applying equipment modifiers for entity {entity.id}: {e}", exc_info=True)
    else:
        logger.debug(f"StatsCalculator: EquipmentManager or ItemManager not available for entity {entity.id}.")

    # 2. Status Effect Modifiers
    if game_manager.status_manager:
        try:
            active_statuses: List[Status] = [] # Type hint with SQLAlchemy Status
            if hasattr(game_manager.status_manager, 'get_active_statuses_for_entity'):
                active_statuses = await game_manager.status_manager.get_active_statuses_for_entity(
                    entity_id=str(entity.id),
                    entity_type=entity_type_str, # Pass determined entity_type
                    guild_id=guild_id
                )
            else:
                logger.debug(f"StatsCalculator: StatusManager missing 'get_active_statuses_for_entity' for entity {entity.id}")

            for status in active_statuses: # status is now expected to be an SQLAlchemy Status model instance
                if hasattr(status, 'effects') and isinstance(status.effects, dict): # Accessing effects directly
                    # Example status.effects structure: {"stat_change": {"strength": -2, "dexterity": 2}, "ac_bonus": 1, "attack_melee_bonus": 1}
                    for effect_type, effect_detail in status.effects.items():
                        if effect_type == "stat_change" and isinstance(effect_detail, dict):
                            for stat_name, mod_value in effect_detail.items():
                                effective_stats[stat_name] = effective_stats.get(stat_name, 0) + int(mod_value)
                        elif effect_type.endswith("_bonus"):
                            # Maps "ac_bonus" from status to "armor_class_bonus" in `bonuses` dict
                            # Maps "attack_melee_bonus" to "attack_bonus_melee" (swapping order)
                            formatted_bonus_key = effect_type # default
                            if effect_type == "ac_bonus":
                                formatted_bonus_key = "armor_class_bonus"
                            elif effect_type == "attack_melee_bonus":
                                formatted_bonus_key = "attack_bonus_melee"
                            elif effect_type == "attack_ranged_bonus":
                                formatted_bonus_key = "attack_bonus_ranged"
                            elif effect_type == "damage_melee_bonus":
                                formatted_bonus_key = "damage_bonus_melee"
                            elif effect_type == "damage_ranged_bonus":
                                formatted_bonus_key = "damage_bonus_ranged"

                            if formatted_bonus_key in bonuses:
                                bonuses[formatted_bonus_key] += int(effect_detail)
                            else:
                                logger.warning(f"StatsCalculator: Unhandled bonus key '{formatted_bonus_key}' (from status effect_type '{effect_type}') from status {getattr(status, 'name', 'Unknown')} for entity {entity.id}")
        except Exception as e:
            logger.error(f"StatsCalculator: Error applying status effect modifiers for entity {entity.id}: {e}", exc_info=True)
    else:
        logger.debug(f"StatsCalculator: StatusManager not available for entity {entity.id}.")

    # 3. Passive Ability Modifiers (Placeholder)
    # ... (conceptual placeholder as in prompt)

    # 4. Derived Stats Calculation
    # Ensure all values used in calculations are numbers, defaulting if necessary
    con_val = int(effective_stats.get("constitution", 10))
    dex_val = int(effective_stats.get("dexterity", 10))
    str_val = int(effective_stats.get("strength", 10))
    int_val = int(effective_stats.get("intelligence", 10))

    con_mod = (con_val - 10) // 2
    dex_mod = (dex_val - 10) // 2
    str_mod = (str_val - 10) // 2
    int_mod = (int_val - 10) // 2

    base_hp_rule_val = await game_manager.get_rule(guild_id, "rules.combat.base_hp", 10)
    hp_per_con_point_rule_val = await game_manager.get_rule(guild_id, "rules.combat.hp_per_con_point", 2)
    bonus_max_hp_val = int(effective_stats.get("bonus_max_hp", 0))
    effective_stats["max_hp"] = int(base_hp_rule_val) + (con_val * int(hp_per_con_point_rule_val)) + bonus_max_hp_val

    base_ac_rule_val = await game_manager.get_rule(guild_id, "rules.combat.base_ac", 10)
    armor_class_bonus_val = int(bonuses.get("armor_class_bonus", 0))
    effective_stats["armor_class"] = int(base_ac_rule_val) + dex_mod + armor_class_bonus_val

    level_val = 1
    try:
        level_val = int(effective_stats.get("level", getattr(entity, 'level', 1)))
        if level_val < 1: level_val = 1
    except (ValueError, TypeError):
        logger.warning(f"StatsCalculator: Could not parse level for entity {entity.id}. Defaulting to 1.")
        level_val = 1


    proficiency_bonus_per_level_rule_val = await game_manager.get_rule(guild_id, "rules.character.proficiency_bonus_per_level", 0.25)
    base_proficiency_bonus_val = await game_manager.get_rule(guild_id, "rules.character.base_proficiency_bonus", 2)
    proficiency_bonus = int(base_proficiency_bonus_val) + int((level_val -1) * float(proficiency_bonus_per_level_rule_val))

    attack_bonus_melee_val = int(bonuses.get("attack_bonus_melee", 0))
    effective_stats["attack_bonus_melee"] = str_mod + proficiency_bonus + attack_bonus_melee_val

    attack_bonus_ranged_val = int(bonuses.get("attack_bonus_ranged", 0))
    effective_stats["attack_bonus_ranged"] = dex_mod + proficiency_bonus + attack_bonus_ranged_val

    damage_bonus_melee_val = int(bonuses.get("damage_bonus_melee", 0))
    effective_stats["damage_bonus_melee"] = str_mod + damage_bonus_melee_val

    damage_bonus_ranged_val = int(bonuses.get("damage_bonus_ranged", 0))
    effective_stats["damage_bonus_ranged"] = dex_mod + damage_bonus_ranged_val

    spell_dc_base_rule_val = await game_manager.get_rule(guild_id, "rules.magic.spell_dc_base", 8)
    effective_stats["spell_save_dc"] = int(spell_dc_base_rule_val) + proficiency_bonus + int_mod
    effective_stats["spell_attack_bonus"] = proficiency_bonus + int_mod

    effective_stats["proficiency_bonus"] = proficiency_bonus

    logger.debug(f"StatsCalculator: Calculated effective stats for entity {getattr(entity, 'id', 'Unknown')}: {effective_stats}")
    return effective_stats
